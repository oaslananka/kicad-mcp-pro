import assert from "node:assert/strict";
import {createHash,createHmac,generateKeyPairSync,randomBytes,randomUUID,sign} from "node:crypto";
import {execFileSync} from "node:child_process";
import {mkdtemp,readFile,rm} from "node:fs/promises";
import {request as httpsRequest,type Server} from "node:https";
import {createServer as createTcpServer} from "node:net";
import type {AddressInfo} from "node:net";
import {tmpdir} from "node:os";
import path from "node:path";
import {test} from "node:test";
import type {Pool} from "pg";
import type {AuthenticationResponseJSON} from "@simplewebauthn/server";
import {inIsolatedDatabase} from "./isolated-db.js";
import {PgOwnerReadWebAuthnIssuer,type OwnerReadApprovalIntent}
  from "../src/owner-read-webauthn-issuer.js";
import {createOwnerReadReviewHandler}
  from "../src/owner-read-review-http.js";
import {createOwnerAcceptanceServer} from "../src/owner-acceptance-server.js";
import {createIdentity} from "../src/identity.js";
import {createIndependentOwnerSessionVerifier}
  from "../src/owner-read-better-auth-session.js";
import {createSignedOwnerIntentDelivery,createVerifiedOwnerIntentIntake}
  from "../src/owner-read-intent-transfer.js";

const source=process.env.TEST_DATABASE_URL;
const owner="owner-reviewed-fixture";
const cloudOrigin="https://cloud.example.test";
const role="cloud_review_issuer_fixture";
const password="isolated_fixture_only";
function credential(){
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
function validAssertion(
  key:ReturnType<typeof credential>,challenge:string,origin:string,
  count:number
):AuthenticationResponseJSON{
  const data=Buffer.alloc(37);
  createHash("sha256").update(new URL(origin).hostname).digest().copy(data,0);
  data[32]=0x05; // User present + user verified; synthetic P-256 fixture.
  data.writeUInt32BE(count,33);
  const client=Buffer.from(JSON.stringify({
    type:"webauthn.get",challenge,origin,crossOrigin:false
  }));
  const signature=sign("sha256",Buffer.concat([
    data,createHash("sha256").update(client).digest()
  ]),key.keys.privateKey);
  return {id:key.id,rawId:key.id,type:"public-key",
    clientExtensionResults:{},response:{
      authenticatorData:data.toString("base64url"),
      clientDataJSON:client.toString("base64url"),
      signature:signature.toString("base64url")
    }};
}
type Reply={status:number;body:string};
function call(
  port:number,ca:Buffer,pathname:string,
  extras:{cookie?:string;origin?:string;body?:object}={}
):Promise<Reply>{
  return new Promise((resolve,reject)=>{
    const payload=extras.body?JSON.stringify(extras.body):undefined;
    const req=httpsRequest({
      hostname:"127.0.0.1",port,servername:"localhost",ca,method:payload?"POST":"GET",
      path:pathname,headers:{
        Host:"localhost:"+port,
        ...(extras.cookie?{Cookie:extras.cookie}:{}),
        ...(payload?{"Content-Type":"application/json",
          Origin:extras.origin??"https://localhost:"+port,
          "Sec-Fetch-Site":"same-origin"}:{})
      },timeout:8_000
    },res=>{
      const chunks:Buffer[]=[];
      res.on("data",(part:Buffer)=>chunks.push(Buffer.from(part)));
      res.on("end",()=>resolve({status:res.statusCode??0,
        body:Buffer.concat(chunks).toString("utf8")}));
      res.on("error",reject);
    });
    req.on("error",reject);
    req.end(payload);
  });
}
test("independent HTTPS owner review accepts only explicit verified WebAuthn scope",
  {skip:!source,timeout:70_000},async()=>{
    await inIsolatedDatabase(source!,[
      "003_better_auth.pgsql","013_owner_read_approvals.pgsql","014_owner_read_approval_replay_guard.pgsql",
      "015_owner_read_webauthn_issuer.pgsql",
      "017_owner_read_webauthn_challenge_one_use.pgsql"
    ],async db=>{
      const schema=(await db.query<{schema:string}>(
        "SELECT current_schema() AS schema")).rows[0]?.schema;
      assert.match(schema??"",/^fixture_[a-f0-9]{18}$/);
      await db.query(
        "CREATE ROLE cloud_review_issuer_fixture LOGIN PASSWORD 'isolated_fixture_only'");
      const key=credential();
      let issuerDb:Pool|undefined,server:Server|undefined;
      const dir=await mkdtemp(path.join(tmpdir(),"cloud-review-http-"));
      try{
        await db.query(
          "DO $role$ BEGIN EXECUTE format("+
          "'GRANT USAGE ON SCHEMA %I TO cloud_review_issuer_fixture',"+
          "current_schema()); END $role$");
        await db.query(
          "GRANT SELECT ON owner_read_passkeys TO cloud_review_issuer_fixture");
        await db.query(
          "GRANT UPDATE(sign_count) ON owner_read_passkeys TO cloud_review_issuer_fixture");
        await db.query(
          "GRANT SELECT,INSERT ON owner_read_webauthn_challenges TO cloud_review_issuer_fixture");
        await db.query(
          "GRANT UPDATE(used_at) ON owner_read_webauthn_challenges TO cloud_review_issuer_fixture");
        await db.query(
          "GRANT INSERT ON owner_read_approvals TO cloud_review_issuer_fixture");
        await db.query(
          "INSERT INTO owner_read_passkeys(credential_id,owner_sub,public_key,enabled) "+
          "VALUES($1,$2,$3,true)",[key.id,owner,key.publicKey]);
        const scoped=new URL(source!);
        scoped.username=role;scoped.password=password;
        scoped.searchParams.set("options","-c search_path="+schema);
        const {Pool}=await import("pg");
        issuerDb=new Pool({connectionString:scoped.toString(),max:4});
        const cert=path.join(dir,"cert.pem"),privateKey=path.join(dir,"key.pem");
        execFileSync("openssl",["req","-x509","-newkey","rsa:2048",
          "-sha256","-nodes","-days","1","-keyout",privateKey,"-out",cert,
          "-subj","/CN=localhost",
          "-addext","subjectAltName=DNS:localhost"],{stdio:"ignore"});
        const reservation=createTcpServer();
        await new Promise<void>(r=>reservation.listen(0,"::",r));
        const info=reservation.address() as AddressInfo;
        const origin="https://localhost:"+info.port;
        await new Promise<void>(r=>reservation.close(()=>r()));
        const authSecret=randomBytes(48).toString("hex");
        const csrfKey=randomBytes(48);
        const sessionId=randomUUID();
        const token=randomBytes(32).toString("base64url");
        await db.query('INSERT INTO "users"("id","name","email","emailVerified")'+
          ' VALUES($1,$2,$3,true)',[
            owner,"Review owner","owner-review@test.invalid"
          ]);
        await db.query('INSERT INTO "session"'+
          '("id","expiresAt","token","updatedAt","userId")'+
          ' VALUES($1,$2,$3,$4,$5)',[
            sessionId,new Date(Date.now()+20*60_000),token,new Date(),owner
          ]);
        const otherId=randomUUID(),otherToken=randomBytes(32).toString("base64url");
        await db.query('INSERT INTO "users"("id","name","email","emailVerified")'+
          ' VALUES($1,$2,$3,true)',[
            "untrusted-other-owner","Other user","other-owner@test.invalid"
          ]);
        await db.query('INSERT INTO "session"'+
          '("id","expiresAt","token","updatedAt","userId")'+
          ' VALUES($1,$2,$3,$4,$5)',[
            otherId,new Date(Date.now()+20*60_000),otherToken,
            new Date(),"untrusted-other-owner"
          ]);
        const otherCookie="__Secure-better-auth.session_token="+
          encodeURIComponent(otherToken+"."+
            createHmac("sha256",authSecret).update(otherToken).digest("base64"));
        const identity=createIdentity({
          publicOrigin:origin,audience:origin+"/mcp",databaseUrl:source!
        },{
          secret:authSecret,googleId:"",googleSecret:"",
          githubId:"synthetic-review-provider",
          githubSecret:"synthetic-review-secret"
        },db);
        const authenticate=createIndependentOwnerSessionVerifier(
          identity,origin,owner,csrfKey
        );
        const cookie="__Secure-better-auth.session_token="+encodeURIComponent(
          token+"."+createHmac("sha256",authSecret).update(token).digest("base64")
        );
        const csrf=createHmac("sha256",csrfKey).update(JSON.stringify([
          "owner-passkey-registration-session-v1",origin,owner,sessionId,token
        ])).digest("base64url");
        const handle=createOwnerReadReviewHandler(
          new PgOwnerReadWebAuthnIssuer(issuerDb,origin),origin,
          authenticate,await readFile(new URL("../src/owner-read-review-client.js",
            import.meta.url))
        );
        const registration={
          begin:async()=>null,complete:async()=>null
        } as unknown as Parameters<typeof createOwnerAcceptanceServer>[0]["registration"];
        const keys=generateKeyPairSync("ed25519");
        const sender=keys.privateKey.export({type:"pkcs8",format:"pem"}).toString();
        const pinned=keys.publicKey.export({type:"spki",format:"pem"}).toString();
        const intake=createVerifiedOwnerIntentIntake(
          origin,cloudOrigin,pinned,async subject=>
            subject===owner?key.id:null,handle
        );
        server=createOwnerAcceptanceServer({
          authorityOrigin:origin,identity,sessionVerifier:authenticate,
          registration,
          tls:{key:await readFile(privateKey),cert:await readFile(cert)},
          clientScript:Buffer.from("/* enrollment fixture */".padEnd(150," ")),
          approval:{receiveSignedIntent:intake,review:handle.handle}
        });
        await new Promise<void>(r=>server!.listen(info.port,"::",r));
        const ca=await readFile(cert);
        const intent=():OwnerReadApprovalIntent=>({
          requestId:randomUUID(),ownerSub:owner,clientId:"trusted-client",
          deviceId:randomUUID(),projectId:randomUUID(),
          origin:cloudOrigin,expiresAtUnixMs:Date.now()+24_000
        });
        const deliver=createSignedOwnerIntentDelivery(
          origin,cloudOrigin,sender,ca);
        const target=intent();
        assert.equal(await deliver({...target,operation:"project_summary"}),
          origin+"/owner-read/review?requestId="+target.requestId);
        assert.equal(await deliver({...target,operation:"project_summary"}),null,
          "Signed intent is single-use");
        const health=await call(info.port,ca,"/health");
        assert.equal(health.status,200);
        assert.deepEqual(JSON.parse(health.body),{
          status:"acceptance_only",registration:"inactive_only",
          activation:"disabled",approval:"webauthn_review_issuer",connector:"disabled"
        });
        assert.equal((await call(info.port,ca,"/api/auth/oauth2/token")).status,404);
        assert.equal((await call(info.port,ca,"/api/v1/connector/ws")).status,404);
        assert.equal((await call(info.port,ca,"/internal/owner-read/intent",{
          body:{requestId:randomUUID(),ownerSub:owner,clientId:"forged"}
        })).status,403);
        assert.equal((await call(info.port,ca,
          "/owner-read/review?requestId="+target.requestId)).status,403);
        assert.equal((await call(info.port,ca,
          "/owner-read/review?requestId="+target.requestId,
          {cookie:otherCookie})).status,403,
          "Valid session of a different owner cannot review this scope");
        assert.equal((await call(info.port,ca,
          "/owner-read/review?requestId="+target.requestId,
          {cookie:"forged-session"})).status,403,
          "Unsigned session cannot browse another owner's scope");
        const reviewed=await call(info.port,ca,
          "/owner-read/review?requestId="+target.requestId,
          {cookie});
        assert.equal(reviewed.status,200);
        assert.match(reviewed.body,/Approve one project summary/);
        const embedded=reviewed.body.match(
          /<script id="request-data" type="application\/json">([^<]+)<\/script>/);
        assert.ok(embedded);
        const data=JSON.parse(embedded[1]) as {
          requestId:string;challenge:string;csrf:string
        };
        assert.equal(data.requestId,target.requestId);
        assert.equal(data.csrf,csrf);
        assert.equal((await db.query(
          "SELECT count(*)::int AS n FROM owner_read_approvals")).rows[0].n,0,
        "A page view or challenge must not authorize a read");
        assert.equal((await call(info.port,ca,"/owner-read/approval",{
          cookie,origin:"https://attacker.example.test",
          body:{requestId:target.requestId,csrf,challenge:data.challenge,
            assertion:validAssertion(key,data.challenge,origin,1)}
        })).status,403,"Cross-site POST never approves");
        assert.equal((await call(info.port,ca,"/owner-read/approval",{
          cookie,body:{
            requestId:target.requestId,csrf:"invalid",challenge:data.challenge,
            assertion:validAssertion(key,data.challenge,origin,1)}
        })).status,403);
        assert.equal((await db.query(
          "SELECT count(*)::int AS n FROM owner_read_approvals")).rows[0].n,0);
        assert.equal((await call(info.port,ca,"/owner-read/approval",{
          cookie,body:{requestId:target.requestId,csrf,
            challenge:data.challenge,
            assertion:validAssertion(key,data.challenge,origin,1)}
        })).status,204,"User-verified independent passkey yields exact one-shot receipt");
        const receipt=await db.query<{
          owner_sub:string;client_id:string;device_id:string;project_id:string;
          cloud_origin:string;operation:string;consumed_at:Date|null
        }>("SELECT owner_sub,client_id,device_id,project_id,cloud_origin,"+
          "operation,consumed_at FROM owner_read_approvals WHERE request_id=$1",
          [target.requestId]);
        assert.equal(receipt.rowCount,1);
        assert.deepEqual(receipt.rows[0],{
          owner_sub:owner,client_id:target.clientId,device_id:target.deviceId,
          project_id:target.projectId,cloud_origin:target.origin,
          operation:"project_summary",consumed_at:null
        });
        assert.equal((await call(info.port,ca,"/owner-read/approval",{
          cookie,body:{requestId:target.requestId,csrf,
            challenge:data.challenge,
            assertion:validAssertion(key,data.challenge,origin,2)}
        })).status,403,"Used approval cannot be replayed");
        assert.equal((await call(info.port,ca,
          "/owner-read/review?requestId="+target.requestId,
          {cookie})).status,404);
        // Browser may not supply a new owner intent from its body or URL.
        const forged=intent();
        assert.equal((await call(info.port,ca,
          "/owner-read/review?requestId="+forged.requestId,
          {cookie})).status,404);
        // An invalid passkey signature must never create a receipt, and
        // the same request must not be retryable with a corrected proof.
        const rejected=intent();
        assert.ok(await deliver({...rejected,operation:"project_summary"}));
        const rejectedPage=await call(info.port,ca,
          "/owner-read/review?requestId="+rejected.requestId,
          {cookie});
        assert.equal(rejectedPage.status,200);
        const rejectedData=rejectedPage.body.match(
          /<script id="request-data" type="application\/json">([^<]+)<\/script>/);
        assert.ok(rejectedData);
        const rejectedChallenge=(JSON.parse(rejectedData[1]) as {
          challenge:string
        }).challenge;
        const signed=validAssertion(key,rejectedChallenge,origin,2);
        signed.response.signature=randomBytes(70).toString("base64url");
        assert.equal((await call(info.port,ca,"/owner-read/approval",{
          cookie,body:{requestId:rejected.requestId,csrf,
            challenge:rejectedChallenge,assertion:signed}
        })).status,403);
        assert.equal((await call(info.port,ca,"/owner-read/approval",{
          cookie,body:{requestId:rejected.requestId,csrf,
            challenge:rejectedChallenge,
            assertion:validAssertion(key,rejectedChallenge,origin,2)}
        })).status,403,"A failed WebAuthn signature burns the approval attempt");
        assert.equal((await db.query(
          "SELECT count(*)::int AS n FROM owner_read_approvals")).rows[0].n,1,
          "Only the deliberate verified action ever produced one receipt");
        const afterRevocation=intent();
        assert.ok(await deliver({...afterRevocation,operation:"project_summary"}));
        await db.query('DELETE FROM "session" WHERE "id"=$1',[sessionId]);
        assert.equal((await call(info.port,ca,
          "/owner-read/review?requestId="+afterRevocation.requestId,
          {cookie})).status,403,
          "A revoked real Better Auth session cannot begin another review");
        assert.equal((await db.query(
          "SELECT count(*)::int AS n FROM owner_read_approvals")).rows[0].n,1,
          "A signed scope cannot override a revoked human session");
      }finally{
        if(server)await new Promise<void>(r=>server!.close(()=>r()));
        await issuerDb?.end();
        await rm(dir,{recursive:true,force:true});
        await db.query("DROP OWNED BY cloud_review_issuer_fixture");
        await db.query("DROP ROLE cloud_review_issuer_fixture");
      }
    });
  });
