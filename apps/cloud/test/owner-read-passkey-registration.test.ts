import assert from "node:assert/strict";
import {randomUUID} from "node:crypto";
import {execFileSync} from "node:child_process";
import {mkdtemp,readFile,rm} from "node:fs/promises";
import {createServer,type Server} from "node:https";
import {tmpdir} from "node:os";
import path from "node:path";
import {test} from "node:test";
import {Pool,type Pool as PoolType} from "pg";
import {chromium} from "playwright";
import type {RegistrationResponseJSON} from "@simplewebauthn/server";
import {inIsolatedDatabase} from "./isolated-db.js";
import {PgOwnerReadPasskeyRegistration}
  from "../src/owner-read-passkey-registration.js";

const url=process.env.TEST_DATABASE_URL;
async function withRole(admin:PoolType,action:(db:PoolType)=>Promise<void>){
  const schema=(await admin.query<{name:string}>(
    "SELECT current_schema() AS name")).rows[0]?.name;
  if(!schema||!/^fixture_[0-9a-f]{18}$/.test(schema))
    throw Error("Not an isolated test schema");
  await admin.query(
    "CREATE ROLE cloud_reg_fixture LOGIN PASSWORD 'test_only_isolated_registration'");
  let db:PoolType|undefined;
  try{
    await admin.query("DO $grant$ BEGIN EXECUTE format("+
      "'GRANT USAGE ON SCHEMA %I TO cloud_reg_fixture',"+
      "current_schema()); END $grant$");
    await admin.query("GRANT SELECT ON owner_read_passkeys TO cloud_reg_fixture");
    await admin.query("GRANT INSERT(credential_id,owner_sub,public_key,sign_count) "+
      "ON owner_read_passkeys TO cloud_reg_fixture");
    await admin.query("GRANT SELECT,INSERT ON owner_read_passkey_registrations "+
      "TO cloud_reg_fixture");
    await admin.query("GRANT UPDATE(used_at) ON owner_read_passkey_registrations "+
      "TO cloud_reg_fixture");
    const target=new URL(url!);
    target.searchParams.set("options","-c search_path="+schema);
    target.username="cloud_reg_fixture";
    target.password="test_only_isolated_registration";
    db=new Pool({connectionString:target.toString(),max:2});
    assert.equal((await db.query<{who:string}>(
      "SELECT current_user AS who")).rows[0]?.who,"cloud_reg_fixture");
    await action(db);
  }finally{
    await db?.end();
    await admin.query("DROP OWNED BY cloud_reg_fixture");
    await admin.query("DROP ROLE cloud_reg_fixture");
  }
}

test("Chrome registration produces only an inactive passkey under SQL role isolation",
  {skip:!url,timeout:85_000},async()=>{
  await inIsolatedDatabase(url!,[
    "013_owner_read_approvals.pgsql",
    "014_owner_read_approval_replay_guard.pgsql",
    "015_owner_read_webauthn_issuer.pgsql",
    "016_owner_read_passkey_registration.pgsql"
  ],async admin=>{
    await withRole(admin,async restricted=>{
      const dir=await mkdtemp(path.join(tmpdir(),"cloud-enrollment-"));
      let server:Server|undefined;
      let browser:Awaited<ReturnType<typeof chromium.launch>>|undefined;
      try{
        const privateKey=path.join(dir,"key.pem");
        const cert=path.join(dir,"cert.pem");
        execFileSync("openssl",["req","-x509","-newkey","rsa:2048",
          "-sha256","-nodes","-days","1","-keyout",privateKey,
          "-out",cert,"-subj","/CN=localhost",
          "-addext","subjectAltName=DNS:localhost"],{stdio:"ignore"});
        server=createServer({
          key:await readFile(privateKey),cert:await readFile(cert)
        },(_req,res)=>{res.writeHead(200,{"Content-Type":"text/html"});
          res.end("<!doctype html><title>Isolated registration</title>");});
        await new Promise<void>(resolve=>server!.listen(0,"::",resolve));
        const port=server.address();
        assert.ok(port&&typeof port!=="string");
        const origin="https://localhost:"+port.port;
        const registrar=new PgOwnerReadPasskeyRegistration(restricted,origin);
        assert.equal(await new PgOwnerReadPasskeyRegistration(admin,origin)
          .begin("owner",randomUUID()),null,"Superuser cannot enroll");
        const owner="independent-owner";
        const requestId=randomUUID();
        assert.equal(await registrar.begin("","not-uuid"),null);
        const options=await registrar.begin(owner,requestId);
        assert.ok(options);
        assert.equal(options.authenticatorSelection?.userVerification,"required");
        assert.deepEqual(options.pubKeyCredParams.map(p=>p.alg),[-7]);
        const expiry=await admin.query<{duration_ms:number}>(
          "SELECT extract(epoch FROM (expires_at-created_at))*1000 "+
          "AS duration_ms FROM owner_read_passkey_registrations "+
          "WHERE request_id=$1",[requestId]);
        assert.equal(Number(expiry.rows[0]?.duration_ms),120_000,
          "Issue time and expiry use one statement clock, no microsecond drift");
        browser=await chromium.launch({channel:"chrome",headless:true});
        const context=await browser.newContext({ignoreHTTPSErrors:true});
        try{
          const page=await context.newPage();
          const cdp=await context.newCDPSession(page);
          await cdp.send("WebAuthn.enable");
          await cdp.send("WebAuthn.addVirtualAuthenticator",{options:{
            protocol:"ctap2",transport:"internal",
            hasResidentKey:true,hasUserVerification:true,isUserVerified:true,
            automaticPresenceSimulation:true
          }});
          await page.goto(origin);
          const registration=await page.evaluate(`(async()=>{
            const options=${JSON.stringify(options)};
            const decode=(value)=>Uint8Array.from(atob(
              value.replace(/-/g,"+").replace(/_/g,"/")+
              "=".repeat((4-value.length%4)%4)),c=>c.charCodeAt(0));
            const credential=await navigator.credentials.create({publicKey:{
              ...options,challenge:decode(options.challenge),
              user:{...options.user,id:decode(options.user.id)},
              excludeCredentials:[]
            }});
            if(!credential||typeof credential.toJSON!=="function")
              throw Error("Cannot enroll virtual passkey");
            return credential.toJSON();
          })()`) as RegistrationResponseJSON;
          assert.equal(await registrar.complete(owner,requestId,registration),
            "registered_inactive");
          assert.equal(await registrar.complete(owner,requestId,registration),"denied",
            "A registration challenge is one-time");
          // Regression: a valid challenge plus broken attestation reaches the
          // signature verifier; it must be burned despite verifier failure.
          const invalidProofRequest=randomUUID();
          const invalidProofOptions=await registrar.begin(owner,invalidProofRequest);
          assert.ok(invalidProofOptions);
          const invalidProofRegistration=await page.evaluate(`(async()=>{
            const options=${JSON.stringify(invalidProofOptions)};
            const decode=(value)=>Uint8Array.from(atob(
              value.replace(/-/g,"+").replace(/_/g,"/")+
              "=".repeat((4-value.length%4)%4)),c=>c.charCodeAt(0));
            const credential=await navigator.credentials.create({publicKey:{
              ...options,challenge:decode(options.challenge),
              user:{...options.user,id:decode(options.user.id)},
              excludeCredentials:[]
            }});
            if(!credential||typeof credential.toJSON!=="function")
              throw Error("Cannot create registration for replay regression");
            return credential.toJSON();
          })()`) as RegistrationResponseJSON;
          const invalidAttestation={
            ...invalidProofRegistration,
            response:{...invalidProofRegistration.response,attestationObject:"AA"}
          };
          assert.equal(await registrar.complete(owner,invalidProofRequest,invalidAttestation),
            "denied","Malformed attestation must fail verification");
          assert.equal(await registrar.complete(owner,invalidProofRequest,invalidProofRegistration),
            "denied","Failed attestation must permanently burn the matching challenge");
          const persisted=await admin.query<{used_at:Date|null}>(
            "SELECT used_at FROM owner_read_passkey_registrations "+
            "WHERE request_id=$1",[invalidProofRequest]);
          assert.ok(persisted.rows[0]?.used_at,"Failed cryptography must commit consumed state");
          const tamperedRequest=randomUUID();
          assert.ok(await registrar.begin(owner,tamperedRequest));
          const wrongOwner=await registrar.complete("another-owner",
            tamperedRequest,registration);
          assert.equal(wrongOwner,"denied","Cross-owner registration cannot complete");
          const malformed={
            ...registration,
            response:{...registration.response,clientDataJSON:Buffer.from(
              JSON.stringify({type:"webauthn.create",
                challenge:"fabricated",origin:"https://evil.example.test"})
            ).toString("base64url")}
          };
          assert.equal(await registrar.complete(owner,tamperedRequest,malformed),
            "denied","Forged registration client data must be refused");
          assert.equal(await registrar.complete(owner,tamperedRequest,registration),
            "denied","Even invalid attempts consume the challenge");
          await assert.rejects(restricted.query(
            "UPDATE owner_read_passkey_registrations SET used_at=NULL WHERE request_id=$1",
            [tamperedRequest]),/already consumed/);
          const expiredRequest=randomUUID();
          assert.ok(await registrar.begin(owner,expiredRequest));
          await admin.query(
            "UPDATE owner_read_passkey_registrations "+
            "SET created_at=clock_timestamp()-interval '100 seconds', "+
            "expires_at=clock_timestamp()-interval '1 second' "+
            "WHERE request_id=$1",[expiredRequest]);
          assert.equal(await registrar.complete(owner,expiredRequest,registration),
            "denied","Expired registration cannot be redeemed");
          const rows=await admin.query<{enabled:boolean;owner_sub:string}>(
            "SELECT enabled,owner_sub FROM owner_read_passkeys");
          assert.equal(rows.rowCount,1);
          assert.equal(rows.rows[0]?.enabled,false);
          assert.equal(rows.rows[0]?.owner_sub,owner);
          assert.equal((await admin.query(
            "SELECT count(*)::integer AS count FROM owner_read_approvals")
          ).rows[0]?.count,0);
          await assert.rejects(restricted.query(
            "UPDATE owner_read_passkeys SET enabled=true"),
            (e:unknown)=>Boolean(e&&typeof e==="object"&&
              "code" in e&&e.code==="42501"));
        }finally{await context.close();}
      }finally{
        await browser?.close();
        if(server)await new Promise<void>(r=>server!.close(()=>r()));
        await rm(dir,{recursive:true,force:true});
      }
    });
  });
});
