import assert from "node:assert/strict";
import {execFileSync} from "node:child_process";
import {generateKeyPairSync,randomBytes,randomUUID} from "node:crypto";
import {mkdtemp,readFile,rm,writeFile} from "node:fs/promises";
import {request as httpsRequest} from "node:https";
import {createServer as createTcpServer} from "node:net";
import type {AddressInfo} from "node:net";
import {tmpdir} from "node:os";
import path from "node:path";
import {test} from "node:test";
import type {Pool} from "pg";
import {inIsolatedDatabase} from "./isolated-db.js";
import {startOwnerReviewAuthority} from "../src/owner-review-cli.js";
import {createSignedOwnerIntentDelivery} from "../src/owner-read-intent-transfer.js";

const database=process.env.TEST_DATABASE_URL;
const cloudOrigin="https://cloud.example.test";
async function httpStatus(port:number,ca:Buffer,route:string):Promise<number>{
  return new Promise((resolve,reject)=>{
    const request=httpsRequest({
      hostname:"127.0.0.1",port,servername:"localhost",
      ca,path:route,timeout:3_000,
      headers:{Host:"localhost:"+port}
    },response=>{
      response.resume();
      response.on("end",()=>resolve(response.statusCode??0));
      response.on("error",reject);
    });
    request.on("error",reject);
    request.end();
  });
}
test("issuer CLI defaults disabled with no implicit credentials",async()=>{
  await assert.rejects(startOwnerReviewAuthority({}),/explicit opt-in/);
  await assert.rejects(startOwnerReviewAuthority({
    OWNER_REVIEW_ENABLED:"false"
  }),/explicit opt-in/);
  await assert.rejects(startOwnerReviewAuthority({
    OWNER_REVIEW_ENABLED:"true"
  }),/Missing independent owner issuer setting/);
});

test("standalone owner issuer accepts only separate restricted SQL login roles",
  {skip:!database,timeout:60_000},async()=>{
  await inIsolatedDatabase(database!,[
    "003_better_auth.pgsql",
    "013_owner_read_approvals.pgsql",
    "014_owner_read_approval_replay_guard.pgsql",
    "015_owner_read_webauthn_issuer.pgsql",
    "016_owner_read_passkey_registration.pgsql",
    "017_owner_read_webauthn_challenge_one_use.pgsql"
  ],async admin=>{
    const schema=(await admin.query<{schema:string}>(
      "SELECT current_schema() AS schema")).rows[0]?.schema;
    assert.match(schema??"",/^fixture_[0-9a-f]{18}$/);
    const dir=await mkdtemp(path.join(tmpdir(),"cloud-review-launcher-"));
    const names=["cloud_owner_cli_id","cloud_owner_cli_reg","cloud_owner_cli_issuer"] as const;
    const creds=new Map<string,string>();
    let launched:Awaited<ReturnType<typeof startOwnerReviewAuthority>>|null=null;
    try{
      for(const name of names){
        const password=randomBytes(32).toString("base64url");
        // Static fixture role names and SQL-side quoting, no secret in code.
        const sql=(await admin.query<{command:string}>(
          "SELECT format('CREATE ROLE %I LOGIN PASSWORD %L',$1::text,$2::text) AS command",
          [name,password])).rows[0]?.command;
        assert.ok(sql);await admin.query(sql);creds.set(name,password);
      }
      await admin.query(
        "DO $g$ BEGIN EXECUTE format('GRANT USAGE ON SCHEMA %I TO "+
        "cloud_owner_cli_id,cloud_owner_cli_reg,cloud_owner_cli_issuer',"+
        "current_schema()); END $g$");
      await admin.query(
        'GRANT SELECT,INSERT,UPDATE,DELETE ON "users","session","account",'+
        '"verification","jwks","oauthClient","oauthResource",'+
        '"oauthClientResource","oauthRefreshToken","oauthAccessToken",'+
        '"oauthConsent","oauthClientAssertion" TO cloud_owner_cli_id');
      await admin.query(
        "GRANT SELECT ON owner_read_passkeys TO cloud_owner_cli_reg,cloud_owner_cli_issuer");
      await admin.query(
        "GRANT INSERT(credential_id,owner_sub,public_key,sign_count) ON "+
        "owner_read_passkeys TO cloud_owner_cli_reg");
      await admin.query(
        "GRANT SELECT,INSERT ON owner_read_passkey_registrations TO cloud_owner_cli_reg");
      await admin.query(
        "GRANT UPDATE(used_at) ON owner_read_passkey_registrations TO cloud_owner_cli_reg");
      await admin.query(
        "GRANT SELECT,INSERT ON owner_read_webauthn_challenges TO cloud_owner_cli_issuer");
      await admin.query(
        "GRANT UPDATE(used_at) ON owner_read_webauthn_challenges TO cloud_owner_cli_issuer");
      await admin.query(
        "GRANT UPDATE(sign_count) ON owner_read_passkeys TO cloud_owner_cli_issuer");
      await admin.query(
        "GRANT INSERT ON owner_read_approvals TO cloud_owner_cli_issuer");
      const scopeURL=(name:string)=>{
        const url=new URL(database!);
        url.username=name;
        url.password=creds.get(name)!;
        url.searchParams.set("options","-c search_path="+schema);
        return url.toString();
      };
      const certPath=path.join(dir,"cert.pem"),keyPath=path.join(dir,"key.pem");
      execFileSync("openssl",[
        "req","-x509","-newkey","rsa:2048","-sha256","-nodes",
        "-days","1","-keyout",keyPath,"-out",certPath,
        "-subj","/CN=localhost","-addext","subjectAltName=DNS:localhost"
      ],{stdio:"ignore"});
      const signer=generateKeyPairSync("ed25519");
      const pub=path.join(dir,"cloud-public.pem");
      await writeFile(pub,signer.publicKey.export({type:"spki",format:"pem"}));
      const tcp=createTcpServer();
      await new Promise<void>(resolve=>tcp.listen(0,"127.0.0.1",resolve));
      const port=(tcp.address() as AddressInfo).port;
      await new Promise<void>(resolve=>tcp.close(()=>resolve()));
      const owner="test-review-cli-owner";
      const env={
        OWNER_REVIEW_ENABLED:"true",
        OWNER_REVIEW_ORIGIN:"https://localhost:"+port,
        OWNER_REVIEW_CLOUD_ORIGIN:cloudOrigin,
        OWNER_REVIEW_PORT:String(port),
        OWNER_REVIEW_IDENTITY_DB_URL:scopeURL(names[0]),
        OWNER_REVIEW_REGISTRATION_DB_URL:scopeURL(names[1]),
        OWNER_REVIEW_ISSUER_DB_URL:scopeURL(names[2]),
        OWNER_REVIEW_OWNER_SUB:owner,
        OWNER_REVIEW_BETTER_AUTH_SECRET:randomBytes(48).toString("hex"),
        OWNER_REVIEW_GITHUB_CLIENT_ID:"synthetic-local-oauth-app",
        OWNER_REVIEW_GITHUB_CLIENT_SECRET:randomBytes(32).toString("hex"),
        OWNER_REVIEW_CSRF_KEY:randomBytes(48).toString("base64url"),
        OWNER_REVIEW_TLS_KEY_FILE:keyPath,
        OWNER_REVIEW_TLS_CERT_FILE:certPath,
        OWNER_REVIEW_CLOUD_PUBLIC_KEY_FILE:pub
      };
      assert.match(await readFile(pub,"utf8"),/PUBLIC KEY/);
      await assert.rejects(startOwnerReviewAuthority({
        ...env,OWNER_REVIEW_ISSUER_DB_URL:env.OWNER_REVIEW_REGISTRATION_DB_URL
      }),/startup denied/,"Issuer cannot share the registration principal");
      launched=await startOwnerReviewAuthority(env);
      const cert=await readFile(certPath);
      assert.equal(await httpStatus(port,cert,"/health"),200);
      assert.equal(await httpStatus(port,cert,"/api/auth/oauth2/token"),404);
      assert.equal(await httpStatus(port,cert,"/api/v1/connector/ws"),404);
      assert.equal(await httpStatus(port,cert,"/owner-passkey/activate"),404);
      const deliver=createSignedOwnerIntentDelivery(env.OWNER_REVIEW_ORIGIN,
        cloudOrigin,signer.privateKey.export({
          type:"pkcs8",format:"pem"
        }).toString(),cert);
      const pending={
        requestId:randomUUID(),ownerSub:owner,clientId:"trusted-client",
        deviceId:randomUUID(),projectId:randomUUID(),origin:cloudOrigin,
        operation:"project_summary" as const,
        expiresAtUnixMs:Date.now()+25_000
      };
      assert.equal(await deliver(pending),null,
        "A valid signed request cannot initiate review without an enabled passkey");
      assert.equal(await httpStatus(port,cert,
        "/owner-read/review?requestId="+pending.requestId),403);
      // The CLI may only SELECT an independently activated credential.
      // This fixture inserts the active key as an isolated SQL admin; the
      // issuer login itself has no enabled/activation write permission.
      await admin.query(
        "INSERT INTO owner_read_passkeys"+
        "(credential_id,owner_sub,public_key,enabled) VALUES($1,$2,$3,true)",
        [randomBytes(32).toString("base64url"),owner,randomBytes(65)]
      );
      const next={
        ...pending,requestId:randomUUID(),
        expiresAtUnixMs:Date.now()+25_000
      };
      assert.equal(await deliver(next),
        env.OWNER_REVIEW_ORIGIN+"/owner-read/review?requestId="+next.requestId,
        "Separate issuer launches real HTTPS signed-intent acceptance");
      assert.equal(await deliver(next),null,
        "Independent intake rejects a replayed signed Cloud request");
      const found=await admin.query<{n:number}>(
        "SELECT count(*)::int AS n FROM owner_read_approvals");
      assert.equal(found.rows[0]?.n,0);
      await launched.close();launched=null;
      await admin.query(
        "GRANT UPDATE(enabled) ON owner_read_passkeys TO cloud_owner_cli_issuer");
      await assert.rejects(startOwnerReviewAuthority(env),/startup denied/,
        "An issuer that can activate credentials cannot open HTTPS listener");
    }finally{
      await launched?.close();
      await rm(dir,{recursive:true,force:true});
      for(const name of [...names].reverse()){
        if(!creds.has(name))continue;
        await admin.query("DROP OWNED BY "+name);
        await admin.query("DROP ROLE "+name);
      }
    }
  });
});
