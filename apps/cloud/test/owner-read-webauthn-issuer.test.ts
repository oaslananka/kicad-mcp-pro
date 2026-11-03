import assert from "node:assert/strict";
import {createHash,generateKeyPairSync,randomBytes,randomUUID,sign} from "node:crypto";
import {test} from "node:test";
import {Pool,type Pool as PoolType} from "pg";
import type {AuthenticationResponseJSON} from "@simplewebauthn/server";
import {inIsolatedDatabase} from "./isolated-db.js";
import {PgOwnerReadWebAuthnIssuer,type OwnerReadApprovalIntent}
  from "../src/owner-read-webauthn-issuer.js";

const url=process.env.TEST_DATABASE_URL;
const origin="https://owner.example.test";
const cloudOrigin="https://cloud.example.test";
const owner="verified-browser-owner";
const clientId="registered-mcp-client";
const role="cloud_issuer_fixture";
const password="isolated_fixture_only";
function pair(){
  const keys=generateKeyPairSync("ec",{namedCurve:"prime256v1"});
  const jwk=keys.publicKey.export({format:"jwk"});
  if(!jwk.x||!jwk.y)throw Error("Missing test key coordinates");
  // COSE EC2 P-256 public key. Encoded solely from synthetic fixture key.
  const cose=Buffer.concat([
    Buffer.from([0xa5,0x01,0x02,0x03,0x26,0x20,0x01,0x21,0x58,0x20]),
    Buffer.from(jwk.x,"base64url"),Buffer.from([0x22,0x58,0x20]),
    Buffer.from(jwk.y,"base64url")
  ]);
  return {keys,cose,id:randomBytes(32).toString("base64url")};
}
type TestKey=ReturnType<typeof pair>;
function intent():OwnerReadApprovalIntent{
  return {requestId:randomUUID(),ownerSub:owner,clientId,
    deviceId:randomUUID(),projectId:randomUUID(),origin:cloudOrigin,
    expiresAtUnixMs:Date.now()+24_000};
}
function assertPasskey(credential:TestKey,challenge:string,options:{
  origin?:string;uv?:boolean;count?:number;rpID?:string;id?:string
}={}):AuthenticationResponseJSON{
  const rpID=options.rpID??new URL(origin).hostname;
  const auth=Buffer.alloc(37);
  createHash("sha256").update(rpID).digest().copy(auth,0);
  auth[32]=(options.uv??true)?0x05:0x01; // UP plus user-verified UV
  auth.writeUInt32BE(options.count??1,33);
  const client=Buffer.from(JSON.stringify({type:"webauthn.get",challenge,
    origin:options.origin??origin,crossOrigin:false}));
  const signature=sign("sha256",Buffer.concat([
    auth,createHash("sha256").update(client).digest()
  ]),credential.keys.privateKey);
  const id=options.id??credential.id;
  return {id,rawId:id,type:"public-key",clientExtensionResults:{},
    response:{authenticatorData:auth.toString("base64url"),
      clientDataJSON:client.toString("base64url"),
      signature:signature.toString("base64url")}};
}

async function withIssuerRole(admin:PoolType,action:(db:PoolType)=>Promise<void>){
  const schema=(await admin.query<{name:string}>(
    "SELECT current_schema() AS name")).rows[0]?.name;
  if(!schema||!/^fixture_[a-f0-9]{18}$/.test(schema))throw Error("Unsafe fixture schema");
  await admin.query(
    "CREATE ROLE cloud_issuer_fixture LOGIN PASSWORD 'isolated_fixture_only'");
  let db:PoolType|undefined;
  try{
    // SQL statements are static; PostgreSQL quotes isolated schema names.
    await admin.query("DO $code$ BEGIN EXECUTE format("+
      "'GRANT USAGE ON SCHEMA %I TO cloud_issuer_fixture',current_schema()); "+
      "END $code$");
    await admin.query("GRANT SELECT ON owner_read_passkeys TO cloud_issuer_fixture");
    await admin.query("GRANT UPDATE(sign_count) ON owner_read_passkeys TO cloud_issuer_fixture");
    await admin.query(
      "GRANT SELECT,INSERT ON owner_read_webauthn_challenges TO cloud_issuer_fixture");
    await admin.query(
      "GRANT UPDATE(used_at) ON owner_read_webauthn_challenges TO cloud_issuer_fixture");
    await admin.query("GRANT INSERT ON owner_read_approvals TO cloud_issuer_fixture");
    const scoped=new URL(url!);
    scoped.username=role;scoped.password=password;
    scoped.searchParams.set("options","-c search_path="+schema);
    db=new Pool({connectionString:scoped.toString(),max:6});
    assert.equal((await db.query<{who:string}>(
      "SELECT current_user AS who")).rows[0]?.who,role);
    await action(db);
  }finally{
    await db?.end();
    await admin.query("DROP OWNED BY cloud_issuer_fixture");
    await admin.query("DROP ROLE cloud_issuer_fixture");
  }
}

test("independent issuer verifies UV passkey and exact one-use scoped read receipt",
  {skip:!url,timeout:50_000},async()=>{
  await inIsolatedDatabase(url!,[
    "013_owner_read_approvals.pgsql",
    "014_owner_read_approval_replay_guard.pgsql",
    "015_owner_read_webauthn_issuer.pgsql",
    "017_owner_read_webauthn_challenge_one_use.pgsql"
  ],async admin=>{
    const key=pair();
    await admin.query(
      "INSERT INTO owner_read_passkeys(credential_id,owner_sub,public_key,enabled) "+
      "VALUES($1,$2,$3,true)",[key.id,owner,key.cose]);
    await withIssuerRole(admin,async restricted=>{
      const issuer=new PgOwnerReadWebAuthnIssuer(restricted,origin);
      const adminIssuer=new PgOwnerReadWebAuthnIssuer(admin,origin);
      const denied=intent();
      assert.equal(await adminIssuer.begin(denied,key.id),null,
        "Database owner/superuser is not a separately authorized issuer");
      await admin.query(
        "GRANT UPDATE(consumed_at) ON owner_read_approvals TO cloud_issuer_fixture");
      assert.equal(await issuer.begin(intent(),key.id),null,
        "An issuer must not also have the consumer receipt-update privilege");
      await admin.query(
        "REVOKE UPDATE(consumed_at) ON owner_read_approvals FROM cloud_issuer_fixture");
      assert.equal(await issuer.begin({...denied,ownerSub:"forged-owner"},key.id),null);
      assert.equal(await issuer.begin({...denied,origin:"http://owner.example.test"},key.id),null);
      const allowed=intent();
      const options=await issuer.begin(allowed,key.id);
      assert.ok(options);
      assert.equal(options.userVerification,"required");
      assert.equal(options.rpId,new URL(origin).hostname);
      assert.notEqual(options.rpId,new URL(cloudOrigin).hostname,
        "Passkey must be scoped to independent approval authority");
      assert.deepEqual(options.allowCredentials?.map(x=>x.id),[key.id]);
      assert.equal(await issuer.approve(allowed.requestId,options.challenge,
        assertPasskey(key,options.challenge)),true,
      "Valid P-256 WebAuthn UV signature yields a bound receipt");
      const stored=await admin.query(
        "SELECT owner_sub,client_id,device_id,project_id,cloud_origin,operation "+
        "FROM owner_read_approvals WHERE request_id=$1",[allowed.requestId]);
      assert.equal(stored.rowCount,1);
      assert.deepEqual(stored.rows[0],{
        owner_sub:owner,client_id:clientId,device_id:allowed.deviceId,
        project_id:allowed.projectId,cloud_origin:cloudOrigin,operation:"project_summary"
      });
      assert.equal(await issuer.approve(allowed.requestId,options.challenge,
        assertPasskey(key,options.challenge)),false,"Challenge and receipt cannot replay");
      const count=await admin.query<{sign_count:string}>(
        "SELECT sign_count FROM owner_read_passkeys WHERE credential_id=$1",[key.id]);
      assert.equal(Number(count.rows[0]?.sign_count),1);

      for(const attack of [
        {name:"no user verification",make:(challenge:string)=>
          assertPasskey(key,challenge,{uv:false,count:2})},
        {name:"incorrect origin",make:(challenge:string)=>
          assertPasskey(key,challenge,{origin:"https://evil.example.test",count:2})},
        {name:"incorrect rp ID",make:(challenge:string)=>
          assertPasskey(key,challenge,{rpID:"evil.example.test",count:2})},
        {name:"old authenticator counter",make:(challenge:string)=>
          assertPasskey(key,challenge,{count:1})},
        {name:"forged signature",make:(challenge:string)=>
          assertPasskey(pair(),challenge,{id:key.id,count:2})}
      ]){
        const scoped=intent();
        const issued=await issuer.begin(scoped,key.id);
        assert.ok(issued);
        assert.equal(await issuer.approve(scoped.requestId,issued.challenge,
          attack.make(issued.challenge)),false,attack.name);
        // Invalid attempt permanently burns the challenge.
        assert.equal(await issuer.approve(scoped.requestId,issued.challenge,
          assertPasskey(key,issued.challenge,{count:2})),false,attack.name+" burned");
        assert.equal((await admin.query(
          "SELECT count(*)::integer AS n FROM owner_read_approvals "+
          "WHERE request_id=$1",[scoped.requestId])).rows[0].n,0,attack.name);
      }

      // A restricted issuer role can only UPDATE(used_at), but before
      // migration 017 could reset a rejected proof and redeem it again.
      const resetCandidate=intent();
      const resetOptions=await issuer.begin(resetCandidate,key.id);
      assert.ok(resetOptions);
      assert.equal(await issuer.approve(resetCandidate.requestId,
        resetOptions.challenge,
        assertPasskey(key,resetOptions.challenge,{
          origin:"https://wrong.example.test",count:2
        })),false,"Original invalid WebAuthn attempt must fail");
      await assert.rejects(
        restricted.query(
          "UPDATE owner_read_webauthn_challenges SET used_at=NULL "+
          "WHERE request_id=$1",[resetCandidate.requestId]),
        /challenge already consumed/,
        "A limited issuer role must never reset a used challenge"
      );
      assert.equal(await issuer.approve(resetCandidate.requestId,
        resetOptions.challenge,assertPasskey(key,resetOptions.challenge,{
          count:2
        })),false,"Invalid challenge stays used, even with a valid later signature");
      const revoked=intent();
      const revokedOptions=await issuer.begin(revoked,key.id);
      assert.ok(revokedOptions);
      await admin.query("UPDATE owner_read_passkeys SET enabled=false WHERE credential_id=$1",
        [key.id]);
      assert.equal(await issuer.approve(revoked.requestId,revokedOptions.challenge,
        assertPasskey(key,revokedOptions.challenge,{count:2})),false,
        "Disabling credential after challenge denies approval");
      assert.equal(await issuer.begin(intent(),key.id),null,
        "Revoked credentials cannot issue new challenges");
      assert.equal((await admin.query(
        "SELECT count(*)::integer AS n FROM owner_read_approvals")).rows[0].n,1);
    });
  });
});
