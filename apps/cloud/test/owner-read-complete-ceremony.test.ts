import assert from "node:assert/strict";
import {execFileSync} from "node:child_process";
import {randomUUID} from "node:crypto";
import {mkdtemp,readFile,rm} from "node:fs/promises";
import {createServer,type Server} from "node:https";
import {tmpdir} from "node:os";
import path from "node:path";
import {test} from "node:test";
import type {Pool,PoolClient} from "pg";
import {chromium} from "playwright";
import type {
  AuthenticationResponseJSON,RegistrationResponseJSON
} from "@simplewebauthn/server";
import {inIsolatedDatabase} from "./isolated-db.js";
import {PgOwnerReadPasskeyRegistration}
  from "../src/owner-read-passkey-registration.js";
import {PgOwnerReadPasskeyActivation}
  from "../src/owner-read-passkey-activation.js";
import {PgOwnerReadWebAuthnIssuer}
  from "../src/owner-read-webauthn-issuer.js";
import {PgOwnerReadApprovalLedger}
  from "../src/owner-read-approval-ledger.js";

// All browser identities, PostgreSQL roles, WebAuthn keys and receipts in
// this test are synthetic, temporary and NEVER deployed or enrolled on a
// real owner's computer. This does NOT prove live OAuth/physical KiCad E2E.
const url=process.env.TEST_DATABASE_URL;
const names=["cloud_ceremony_reg","cloud_ceremony_activation",
  "cloud_ceremony_issuer","cloud_ceremony_consumer"] as const;
type Role=typeof names[number];

async function withRoles(db:Pool,action:(roles:Record<Role,Pool>)=>Promise<void>){
  const schema=(await db.query<{name:string}>(
    "SELECT current_schema() AS name")).rows[0]?.name;
  if(!schema||!/^fixture_[0-9a-f]{18}$/.test(schema))
    throw Error("Not an isolated test schema");
  const clients:PoolClient[]=[];
  try{
    // Static fixture-only role names; NOLOGIN, no passwords and no grants
    // to the production app, registered owner, or external service.
    await db.query("CREATE ROLE cloud_ceremony_reg NOLOGIN");
    await db.query("CREATE ROLE cloud_ceremony_activation NOLOGIN");
    await db.query("CREATE ROLE cloud_ceremony_issuer NOLOGIN");
    await db.query("CREATE ROLE cloud_ceremony_consumer NOLOGIN");
    // Note: static role identifiers are hardcoded within this one closed
    // test file; no external strings can reach the SQL role name.
    await db.query("DO $roles$ BEGIN "+
      "EXECUTE format('GRANT USAGE ON SCHEMA %I TO "+
      "cloud_ceremony_reg,cloud_ceremony_activation,"+
      "cloud_ceremony_issuer,cloud_ceremony_consumer',current_schema()); "+
      "END $roles$");
    await db.query("GRANT SELECT ON owner_read_passkeys TO "+
      "cloud_ceremony_reg,cloud_ceremony_activation,cloud_ceremony_issuer");
    await db.query("GRANT INSERT(credential_id,owner_sub,public_key,sign_count) "+
      "ON owner_read_passkeys TO cloud_ceremony_reg");
    await db.query("GRANT SELECT,INSERT ON owner_read_passkey_registrations "+
      "TO cloud_ceremony_reg");
    await db.query("GRANT UPDATE(used_at) ON owner_read_passkey_registrations "+
      "TO cloud_ceremony_reg");
    await db.query("GRANT UPDATE(enabled,sign_count) ON owner_read_passkeys "+
      "TO cloud_ceremony_activation");
    await db.query("GRANT SELECT,INSERT ON owner_read_passkey_activations "+
      "TO cloud_ceremony_activation");
    await db.query("GRANT UPDATE(used_at) ON owner_read_passkey_activations "+
      "TO cloud_ceremony_activation");
    await db.query("GRANT SELECT,INSERT ON owner_read_webauthn_challenges "+
      "TO cloud_ceremony_issuer");
    await db.query("GRANT UPDATE(used_at) ON owner_read_webauthn_challenges "+
      "TO cloud_ceremony_issuer");
    await db.query("GRANT UPDATE(sign_count) ON owner_read_passkeys "+
      "TO cloud_ceremony_issuer");
    await db.query("GRANT INSERT ON owner_read_approvals TO cloud_ceremony_issuer");
    await db.query("GRANT SELECT ON owner_read_approvals TO cloud_ceremony_consumer");
    await db.query("GRANT UPDATE(consumed_at) ON owner_read_approvals "+
      "TO cloud_ceremony_consumer");

    const roles={} as Record<Role,Pool>;
    for(const name of names){
      const conn=await db.connect();
      clients.push(conn);
      // One connection per role: transaction start/claim/commit happen on
      // that same connection. No inherited superuser privileges under SET ROLE.
      switch(name){
        case "cloud_ceremony_reg":
          await conn.query("SET ROLE cloud_ceremony_reg");break;
        case "cloud_ceremony_activation":
          await conn.query("SET ROLE cloud_ceremony_activation");break;
        case "cloud_ceremony_issuer":
          await conn.query("SET ROLE cloud_ceremony_issuer");break;
        case "cloud_ceremony_consumer":
          await conn.query("SET ROLE cloud_ceremony_consumer");break;
      }
      assert.equal((await conn.query<{who:string}>(
        "SELECT current_user AS who")).rows[0]?.who,name);
      const query=conn.query.bind(conn);
      roles[name]={
        query,connect:async()=>({query,release:()=>undefined})
      } as unknown as Pool;
    }
    await action(roles);
  }finally{
    for(const client of clients){
      await client.query("RESET ROLE");
      client.release();
    }
    await db.query("DROP OWNED BY cloud_ceremony_consumer");
    await db.query("DROP ROLE cloud_ceremony_consumer");
    await db.query("DROP OWNED BY cloud_ceremony_issuer");
    await db.query("DROP ROLE cloud_ceremony_issuer");
    await db.query("DROP OWNED BY cloud_ceremony_activation");
    await db.query("DROP ROLE cloud_ceremony_activation");
    await db.query("DROP OWNED BY cloud_ceremony_reg");
    await db.query("DROP ROLE cloud_ceremony_reg");
  }
}

test("Chrome synthetic passkey: register → activate → scope approval → consume, strict privilege separation",
  {skip:!url,timeout:115_000},async()=>{
  await inIsolatedDatabase(url!,[
    "013_owner_read_approvals.pgsql",
    "014_owner_read_approval_replay_guard.pgsql",
    "015_owner_read_webauthn_issuer.pgsql",
    "016_owner_read_passkey_registration.pgsql",
    "017_owner_read_webauthn_challenge_one_use.pgsql",
    "018_owner_read_passkey_activation.pgsql"
  ],async db=>withRoles(db,async roles=>{
    const tmp=await mkdtemp(path.join(tmpdir(),"cloud-passkey-ceremony-"));
    let server:Server|undefined;
    let browser:Awaited<ReturnType<typeof chromium.launch>>|undefined;
    try{
      const key=path.join(tmp,"key.pem"),cert=path.join(tmp,"cert.pem");
      execFileSync("openssl",[
        "req","-x509","-newkey","rsa:2048","-sha256","-nodes",
        "-days","1","-keyout",key,"-out",cert,
        "-subj","/CN=localhost","-addext","subjectAltName=DNS:localhost"
      ],{stdio:"ignore"});
      server=createServer({key:await readFile(key),cert:await readFile(cert)},
        (_req,res)=>{res.writeHead(200,{"Content-Type":"text/html"});
          res.end("<!doctype html><title>Isolated ceremony fixture</title>");});
      await new Promise<void>(resolve=>server!.listen(0,"::",resolve));
      const address=server.address();
      assert.ok(address&&typeof address!=="string");
      const authority="https://localhost:"+address.port;
      const cloudOrigin="https://cloud.example.test";
      const owner="test-owner",clientId="trusted-oauth-client";
      const deviceId=randomUUID(),projectId=randomUUID();
      const registration=new PgOwnerReadPasskeyRegistration(
        roles.cloud_ceremony_reg,authority);
      const activation=new PgOwnerReadPasskeyActivation(
        roles.cloud_ceremony_activation,authority);
      const issuer=new PgOwnerReadWebAuthnIssuer(
        roles.cloud_ceremony_issuer,authority);
      const consumer=new PgOwnerReadApprovalLedger(roles.cloud_ceremony_consumer);
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
        await page.goto(authority);
        const registrationId=randomUUID();
        const enrollment=await registration.begin(owner,registrationId);
        assert.ok(enrollment);
        const response=await page.evaluate(`(async()=>{
          const options=${JSON.stringify(enrollment)};
          const decode=value=>Uint8Array.from(atob(
            value.replace(/-/g,"+").replace(/_/g,"/")+
            "=".repeat((4-value.length%4)%4)),c=>c.charCodeAt(0));
          const credential=await navigator.credentials.create({publicKey:{
            ...options,challenge:decode(options.challenge),
            user:{...options.user,id:decode(options.user.id)},
            excludeCredentials:[]
          }});
          if(!credential||typeof credential.toJSON!=="function")
            throw Error("Credential registration unavailable");
          return credential.toJSON();
        })()`) as RegistrationResponseJSON;
        assert.equal(await registration.complete(owner,registrationId,response),
          "registered_inactive");
        const credentialId=response.id;
        assert.equal(await issuer.begin({
          requestId:randomUUID(),ownerSub:owner,clientId,deviceId,projectId,
          origin:cloudOrigin,expiresAtUnixMs:Date.now()+23_000
        },credentialId),null,"Inactive passkey cannot issue a consent receipt");

        async function authenticate(options:{
          challenge:string;rpId?:string;
          allowCredentials?:Array<{id:string;type:string}>
        }):Promise<AuthenticationResponseJSON>{
          return page.evaluate(`(async()=>{
            const options=${JSON.stringify(options)};
            const decode=value=>Uint8Array.from(atob(
              value.replace(/-/g,"+").replace(/_/g,"/")+
              "=".repeat((4-value.length%4)%4)),c=>c.charCodeAt(0));
            const cred=await navigator.credentials.get({publicKey:{
              ...options,challenge:decode(options.challenge),
              allowCredentials:options.allowCredentials?.map(value=>({
                ...value,id:decode(value.id)
              })),
              userVerification:"required"
            }});
            if(!cred||typeof cred.toJSON!=="function")
              throw Error("Passkey assertion unavailable");
            return cred.toJSON();
          })()`) as Promise<AuthenticationResponseJSON>;
        }
        const pending=await activation.begin(owner,credentialId);
        assert.ok(pending);
        assert.equal(pending.options.userVerification,"required");
        const activationProof=await authenticate(pending.options);
        assert.equal(await activation.complete(owner,pending.requestId,
          pending.options.challenge,activationProof),true);
        assert.equal(await activation.complete(owner,pending.requestId,
          pending.options.challenge,activationProof),false,
          "Activation cannot be replayed");

        const requestId=randomUUID();
        const expiresAtUnixMs=Date.now()+23_000;
        const details={
          requestId,ownerSub:owner,clientId,deviceId,projectId,
          origin:cloudOrigin,expiresAtUnixMs
        };
        const approval=await issuer.begin(details,credentialId);
        assert.ok(approval);
        assert.equal(approval.userVerification,"required");
        assert.equal(approval.rpId,"localhost");
        assert.notEqual(cloudOrigin,authority);
        const scope={oauth:{ownerSub:owner,clientId,
          accessTokenIssuedAtSeconds:Math.floor(Date.now()/1000)},deviceId,projectId,
          requestId,origin:cloudOrigin,expiresAtUnixMs,
          operation:"project_summary" as const};
        assert.equal(await consumer.consume(scope),false,
          "Consumer cannot manufacture authorization before proof");
        const assertion=await authenticate(approval);
        assert.equal(await issuer.approve(requestId,approval.challenge,assertion),
          true,"Registered and activated passkey issues only its scoped read");
        assert.equal(await issuer.approve(requestId,approval.challenge,assertion),
          false,"No second receipt issuance from one passkey challenge");
        const number=(await db.query<{n:number}>(
          "SELECT count(*)::integer AS n FROM owner_read_approvals")
        ).rows[0]?.n;
        assert.equal(number,1);
        assert.equal(await consumer.consume({...scope,oauth:{...scope.oauth,
          clientId:"imposter"}}),false,"Wrong client must not consume");
        assert.equal(await consumer.consume({...scope,projectId:randomUUID()}),
          false,"Wrong project must not consume");
        assert.equal(await consumer.consume(scope),true,
          "Exact scope is consumable once");
        assert.equal(await consumer.consume(scope),false,
          "Consumed receipt cannot be replayed");
        await assert.rejects(roles.cloud_ceremony_consumer.query(
          "UPDATE owner_read_approvals SET consumed_at=NULL WHERE request_id=$1",
          [requestId]),/already consumed/);

        // No single role can manufacture the other three trust stages.
        await assert.rejects(roles.cloud_ceremony_reg.query(
          "UPDATE owner_read_passkeys SET enabled=true WHERE credential_id=$1",
          [credentialId]),(e:unknown)=>Boolean(e&&typeof e==="object"&&
            "code" in e&&e.code==="42501"));
        await assert.rejects(roles.cloud_ceremony_activation.query(
          "INSERT INTO owner_read_approvals(request_id) VALUES(gen_random_uuid())"),
          (e:unknown)=>Boolean(e&&typeof e==="object"&&
            "code" in e&&e.code==="42501"));
      }finally{await context.close();}
    }finally{
      await browser?.close();
      if(server)await new Promise<void>(resolve=>server!.close(()=>resolve()));
      await rm(tmp,{recursive:true,force:true});
    }
  }));
});
