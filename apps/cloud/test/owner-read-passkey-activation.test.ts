import assert from "node:assert/strict";
import {createHash,generateKeyPairSync,randomBytes,sign} from "node:crypto";
import {test} from "node:test";
import type {Pool as PoolType,PoolClient} from "pg";
import type {AuthenticationResponseJSON} from "@simplewebauthn/server";
import {inIsolatedDatabase} from "./isolated-db.js";
import {PgOwnerReadPasskeyActivation}
  from "../src/owner-read-passkey-activation.js";

const url=process.env.TEST_DATABASE_URL;
const origin="https://owner.example.test";
const owner="registered-real-owner-fixture";
const role="cloud_activation_fixture";
function makePasskey(){
  const keys=generateKeyPairSync("ec",{namedCurve:"prime256v1"});
  const jwk=keys.publicKey.export({format:"jwk"});
  assert.ok(jwk.x&&jwk.y);
  const publicKey=Buffer.concat([
    Buffer.from([0xa5,0x01,0x02,0x03,0x26,0x20,0x01,0x21,0x58,0x20]),
    Buffer.from(jwk.x,"base64url"),Buffer.from([0x22,0x58,0x20]),
    Buffer.from(jwk.y,"base64url")
  ]);
  return {keys,publicKey,id:randomBytes(32).toString("base64url")};
}
type Key=ReturnType<typeof makePasskey>;
function assertion(key:Key,challenge:string,{
  uv=true,count=1,badOrigin=false,wrongSig=false
}:{uv?:boolean;count?:number;badOrigin?:boolean;wrongSig?:boolean}={}):
  AuthenticationResponseJSON{
  const bytes=Buffer.alloc(37);
  createHash("sha256").update(new URL(origin).hostname).digest().copy(bytes);
  bytes[32]=uv?0x05:0x01;
  bytes.writeUInt32BE(count,33);
  const clientData=Buffer.from(JSON.stringify({
    type:"webauthn.get",challenge,
    origin:badOrigin?"https://malicious.example.test":origin,
    crossOrigin:false
  }));
  const privateKey=wrongSig?makePasskey().keys.privateKey:key.keys.privateKey;
  const signature=sign("sha256",Buffer.concat([
    bytes,createHash("sha256").update(clientData).digest()
  ]),privateKey);
  return {id:key.id,rawId:key.id,type:"public-key",clientExtensionResults:{},
    response:{
      authenticatorData:bytes.toString("base64url"),
      clientDataJSON:clientData.toString("base64url"),
      signature:signature.toString("base64url")
    }};
}
async function withRole(admin:PoolType,action:(db:PoolType)=>Promise<void>){
  const schema=(await admin.query<{name:string}>(
    "SELECT current_schema() AS name")).rows[0]?.name;
  if(!schema||!/^fixture_[0-9a-f]{18}$/.test(schema))
    throw Error("Unsafe fixture schema");
  await admin.query("CREATE ROLE cloud_activation_fixture NOLOGIN");
  let session:PoolClient|undefined;
  try{
    await admin.query("DO $grant$ BEGIN EXECUTE format("+
      "'GRANT USAGE ON SCHEMA %I TO cloud_activation_fixture',"+
      "current_schema()); END $grant$");
    await admin.query("GRANT SELECT ON owner_read_passkeys "+
      "TO cloud_activation_fixture");
    await admin.query("GRANT UPDATE(enabled,sign_count) ON owner_read_passkeys "+
      "TO cloud_activation_fixture");
    await admin.query("GRANT SELECT,INSERT ON owner_read_passkey_activations "+
      "TO cloud_activation_fixture");
    await admin.query("GRANT UPDATE(used_at) ON owner_read_passkey_activations "+
      "TO cloud_activation_fixture");
    // No static password or user-owned credentials: borrow a single
    // disposable PostgreSQL connection and assume a strict NOLOGIN role.
    // Every call in the activation core is forced through that same role.
    session=await admin.connect();
    await session.query("SET ROLE cloud_activation_fixture");
    const current=(await session.query<{who:string}>(
      "SELECT current_user AS who")).rows[0]?.who;
    assert.equal(current,role);
    const client=session;
    const query=client.query.bind(client);
    const restricted={
      query,
      connect:async()=>({query,release:()=>undefined})
    } as unknown as PoolType;
    await action(restricted);
  }finally{
    if(session){
      await session.query("RESET ROLE");
      session.release();
    }
    await admin.query("DROP OWNED BY cloud_activation_fixture");
    await admin.query("DROP ROLE cloud_activation_fixture");
  }
}
test("separate owner UV passkey activation has limited privileges, one-use assertion and no read receipt",
  {skip:!url,timeout:35_000},async()=>{
  await inIsolatedDatabase(url!,[
    "013_owner_read_approvals.pgsql",
    "014_owner_read_approval_replay_guard.pgsql",
    "015_owner_read_webauthn_issuer.pgsql",
    "016_owner_read_passkey_registration.pgsql",
    "017_owner_read_webauthn_challenge_one_use.pgsql",
    "018_owner_read_passkey_activation.pgsql"
  ],async admin=>{
    const key=makePasskey();
    await admin.query(
      "INSERT INTO owner_read_passkeys(credential_id,owner_sub,public_key) "+
      "VALUES($1,$2,$3)",[key.id,owner,key.publicKey]);
    await withRole(admin,async db=>{
      const activator=new PgOwnerReadPasskeyActivation(db,origin);
      const ownerLevel=new PgOwnerReadPasskeyActivation(admin,origin);
      assert.equal(await ownerLevel.begin(owner,key.id),null,
        "Database owner cannot impersonate restricted activation login");
      assert.equal(await activator.begin("someone-else",key.id),null);
      assert.equal(await activator.begin(owner,"invalid-id"),null);
      assert.equal((await admin.query<{enabled:boolean}>(
        "SELECT enabled FROM owner_read_passkeys WHERE credential_id=$1",
        [key.id])).rows[0]?.enabled,false,"Registration starts inactive");
      await assert.rejects(db.query(
        "UPDATE owner_read_passkeys SET public_key=$1 WHERE credential_id=$2",
        [randomBytes(64),key.id]),
        (err:unknown)=>Boolean(err&&typeof err==="object"&&
          "code" in err&&err.code==="42501"));
      await assert.rejects(db.query(
        "INSERT INTO owner_read_approvals(request_id) VALUES(gen_random_uuid())"),
        (err:unknown)=>Boolean(err&&typeof err==="object"&&
          "code" in err&&err.code==="42501"));

      for(const attack of [
        {label:"missing user verification",opts:{uv:false}},
        {label:"incorrect webauthn origin",opts:{badOrigin:true}},
        {label:"invalid signature",opts:{wrongSig:true}}
      ]){
        const request=await activator.begin(owner,key.id);
        assert.ok(request);
        assert.equal(request.options.userVerification,"required");
        assert.equal(await activator.complete(owner,request.requestId,
          request.options.challenge,assertion(key,request.options.challenge,
            attack.opts)),false,attack.label);
        assert.equal(await activator.complete(owner,request.requestId,
          request.options.challenge,assertion(key,request.options.challenge)),false,
          attack.label+" cannot replay with a valid signature");
        const spent=await admin.query<{used_at:Date|null}>(
          "SELECT used_at FROM owner_read_passkey_activations WHERE request_id=$1",
          [request.requestId]);
        assert.ok(spent.rows[0]?.used_at);
        assert.equal((await admin.query<{enabled:boolean}>(
          "SELECT enabled FROM owner_read_passkeys WHERE credential_id=$1",
          [key.id])).rows[0]?.enabled,false);
      }

      const scope=await activator.begin(owner,key.id);
      assert.ok(scope);
      assert.equal(scope.options.userVerification,"required");
      assert.equal(await activator.complete("another-owner",scope.requestId,
        scope.options.challenge,assertion(key,scope.options.challenge)),false);
      assert.equal(await activator.complete(owner,scope.requestId,
        scope.options.challenge,assertion(key,scope.options.challenge)),true,
        "Signed UV assertion activates an already enrolled inactive credential");
      assert.equal(await activator.complete(owner,scope.requestId,
        scope.options.challenge,assertion(key,scope.options.challenge)),false,
        "Activation proof must not replay");
      const state=await admin.query<{enabled:boolean;sign_count:string}>(
        "SELECT enabled,sign_count FROM owner_read_passkeys WHERE credential_id=$1",
        [key.id]);
      assert.equal(state.rows[0]?.enabled,true);
      assert.equal(Number(state.rows[0]?.sign_count),1);
      assert.equal(await activator.begin(owner,key.id),null,
        "Already active passkey cannot start another activation");

      await assert.rejects(db.query(
        "UPDATE owner_read_passkey_activations SET used_at=NULL WHERE request_id=$1",
        [scope.requestId]),/already used/);
      assert.equal((await admin.query<{n:number}>(
        "SELECT count(*)::integer AS n FROM owner_read_approvals")).rows[0]?.n,0,
        "Activation must not create project-summary read approval");
    });
  });
});
