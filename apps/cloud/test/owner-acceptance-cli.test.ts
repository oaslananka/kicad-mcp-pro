import assert from "node:assert/strict";
import {spawn,execFileSync,type ChildProcess} from "node:child_process";
import {createHmac,randomBytes,randomUUID} from "node:crypto";
import {mkdtemp,readFile,rm} from "node:fs/promises";
import {request as httpsRequest} from "node:https";
import {tmpdir} from "node:os";
import path from "node:path";
import {test} from "node:test";
import {Pool} from "pg";
import {chromium} from "playwright";
import {inIsolatedDatabase} from "./isolated-db.js";

const url=process.env.TEST_DATABASE_URL;
const schemaMigration=[
  "003_better_auth.pgsql","013_owner_read_approvals.pgsql",
  "014_owner_read_approval_replay_guard.pgsql",
  "015_owner_read_webauthn_issuer.pgsql",
  "016_owner_read_passkey_registration.pgsql",
  "017_owner_read_webauthn_challenge_one_use.pgsql",
  "018_owner_read_passkey_activation.pgsql"
];

function httpsStatus(
  port:number,ca:Buffer,route:string,cookie?:string,postBody?:string
):
  Promise<{status:number;body:string}>{
  return new Promise((resolve,reject)=>{
    const req=httpsRequest({hostname:"127.0.0.1",port,
      servername:"localhost",ca,path:route,timeout:2000,
      method:postBody===undefined?"GET":"POST",
      headers:{
        Host:"localhost:"+port,
        ...(cookie?{Cookie:cookie}:{}),
        ...(postBody!==undefined?{
          Origin:"https://localhost:"+port,
          "Content-Type":"application/json",
          "Sec-Fetch-Site":"same-origin"
        }:{})
      }},res=>{
      const chunks:Buffer[]=[];
      res.on("data",(chunk:Buffer)=>chunks.push(Buffer.from(chunk)));
      res.on("end",()=>resolve({status:res.statusCode??0,
        body:Buffer.concat(chunks).toString("utf8")}));
      res.on("error",reject);
    });
    req.on("error",reject);
    req.end(postBody);
  });
}
async function grantLoginRole(db:Pool,role:"cloud_cli_owner_id"|"cloud_cli_owner_reg"){
  await db.query(role==="cloud_cli_owner_id"?
    "CREATE ROLE cloud_cli_owner_id LOGIN":
    "CREATE ROLE cloud_cli_owner_reg LOGIN");
  const password=randomBytes(36).toString("base64url");
  // PostgreSQL utility statements do not support a PASSWORD bind parameter:
  // quote the generated value *inside PostgreSQL* and use fixed role names.
  const sql=(await db.query<{command:string}>(
    role==="cloud_cli_owner_id"?
      "SELECT format('ALTER ROLE cloud_cli_owner_id PASSWORD %L',$1::text) AS command":
      "SELECT format('ALTER ROLE cloud_cli_owner_reg PASSWORD %L',$1::text) AS command",
    [password])).rows[0]?.command;
  assert.ok(sql);
  await db.query(sql);
  return password;
}
test("compiled owner CLI: isolated roles, Chrome WebAuthn and revoked session",
  {skip:!url,timeout:110_000},async()=>{
    await inIsolatedDatabase(url!,schemaMigration,async db=>{
      const schema=(await db.query<{name:string}>(
        "SELECT current_schema() AS name")).rows[0]?.name;
      if(!schema||!/^fixture_[0-9a-f]{18}$/.test(schema))
        throw Error("Unsafe acceptance fixture schema");
      const tmp=await mkdtemp(path.join(tmpdir(),"cloud-owner-cli-e2e-"));
      let proc:ChildProcess|undefined;
      let browser:Awaited<ReturnType<typeof chromium.launch>>|undefined;
      let idCreated=false,regCreated=false;
      try{
        const idPassword=await grantLoginRole(db,"cloud_cli_owner_id");
        idCreated=true;
        const regPassword=await grantLoginRole(db,"cloud_cli_owner_reg");
        regCreated=true;
        await db.query("DO $x$ BEGIN EXECUTE format("+
          "'GRANT USAGE ON SCHEMA %I TO cloud_cli_owner_id,cloud_cli_owner_reg',"+
          "current_schema()); END $x$");
        await db.query('GRANT SELECT,INSERT,UPDATE,DELETE ON "users","session",'+
          '"account","verification","jwks","oauthClient","oauthResource",'+
          '"oauthClientResource","oauthRefreshToken","oauthAccessToken",'+
          '"oauthConsent","oauthClientAssertion" TO cloud_cli_owner_id');
        await db.query("GRANT SELECT ON owner_read_passkeys TO cloud_cli_owner_reg");
        await db.query("GRANT INSERT(credential_id,owner_sub,public_key,sign_count) "+
          "ON owner_read_passkeys TO cloud_cli_owner_reg");
        await db.query("GRANT SELECT,INSERT ON owner_read_passkey_registrations "+
          "TO cloud_cli_owner_reg");
        await db.query("GRANT UPDATE(used_at) ON owner_read_passkey_registrations "+
          "TO cloud_cli_owner_reg");
        const setUrl=(username:string,password:string)=>{
          const result=new URL(url!);
          result.username=username;result.password=password;
          result.searchParams.set("options","-c search_path="+schema);
          return result.toString();
        };
        const idUrl=setUrl("cloud_cli_owner_id",idPassword);
        const regUrl=setUrl("cloud_cli_owner_reg",regPassword);
        const probe=new Pool({connectionString:regUrl});
        try{
          const q=await probe.query<{role:string;schema:string;may_register:boolean}>(
            "SELECT current_user AS role,current_schema() AS schema,"+
            "has_table_privilege(current_user,'owner_read_passkey_registrations','INSERT') AS may_register");
          assert.equal(q.rows[0]?.role,"cloud_cli_owner_reg");
          assert.equal(q.rows[0]?.schema,schema);
          assert.equal(q.rows[0]?.may_register,true);
        }finally{await probe.end();}
        const owner="verified-owner-cli-fixture",sessionId=randomUUID();
        const token=randomBytes(32).toString("base64url");
        const authSecret=randomBytes(48).toString("hex");
        await db.query('INSERT INTO "users"("id","name","email","emailVerified")'+
          ' VALUES($1,$2,$3,true)',[owner,"CLI owner","owner@test.invalid"]);
        await db.query('INSERT INTO "session"'+
          '("id","expiresAt","token","updatedAt","userId")'+
          ' VALUES($1,$2,$3,$4,$5)',[
            sessionId,new Date(Date.now()+15*60_000),token,new Date(),owner
          ]);
        const cert=path.join(tmp,"cert.pem"),key=path.join(tmp,"key.pem");
        execFileSync("openssl",[
          "req","-x509","-newkey","rsa:2048","-sha256","-nodes",
          "-days","1","-keyout",key,"-out",cert,
          "-subj","/CN=localhost","-addext","subjectAltName=DNS:localhost"
        ],{stdio:"ignore"});
        const portServer=await import("node:net");
        const listener=portServer.createServer();
        await new Promise<void>(r=>listener.listen(0,"127.0.0.1",r));
        const address=listener.address();
        assert.ok(address&&typeof address!=="string");
        const port=address.port;
        await new Promise<void>(r=>listener.close(()=>r()));
        const origin="https://localhost:"+port;
        proc=spawn(process.execPath,["dist/owner-acceptance-cli.js"],{
          cwd:process.cwd(),stdio:"ignore",env:{
            ...process.env,
            OWNER_ACCEPTANCE_ORIGIN:origin,
            OWNER_ACCEPTANCE_PORT:String(port),
            OWNER_ACCEPTANCE_IDENTITY_DB_URL:idUrl,
            OWNER_ACCEPTANCE_REGISTRATION_DB_URL:regUrl,
            OWNER_ACCEPTANCE_OWNER_SUB:owner,
            OWNER_ACCEPTANCE_BETTER_AUTH_SECRET:authSecret,
            OWNER_ACCEPTANCE_GITHUB_CLIENT_ID:"synthetic-github-app-local",
            OWNER_ACCEPTANCE_GITHUB_CLIENT_SECRET:randomBytes(32).toString("hex"),
            OWNER_ACCEPTANCE_CSRF_KEY:randomBytes(48).toString("base64url"),
            OWNER_ACCEPTANCE_TLS_KEY_FILE:key,
            OWNER_ACCEPTANCE_TLS_CERT_FILE:cert
          }
        });
        const ca=await readFile(cert);
        let started=false;
        for(let attempt=0;attempt<60;attempt++){
          if(proc.exitCode!==null)break;
          try{
            const health=await httpsStatus(port,ca,"/health");
            if(health.status===200){
              assert.deepEqual(JSON.parse(health.body),{
                status:"acceptance_only",registration:"inactive_only",
                activation:"disabled",approval:"disabled",connector:"disabled"
              });
              started=true;break;
            }
          }catch{ /* Listener has not bound yet. */ }
          await new Promise(r=>setTimeout(r,140));
        }
        assert.equal(started,true,
          "Compiled owner CLI must launch with restricted independent DB roles");
        assert.equal((await httpsStatus(port,ca,"/api/auth/oauth2/token")).status,404);
        assert.equal((await httpsStatus(port,ca,"/owner-passkey/register")).status,403);
        const signedCookie="__Secure-better-auth.session_token="+
          encodeURIComponent(token+"."+
            createHmac("sha256",authSecret).update(token).digest("base64"));
        const signedPage=await httpsStatus(port,ca,
          "/owner-passkey/register",signedCookie);
        assert.equal(signedPage.status,200,
          "Real CLI must accept the owner session via validated HTTPS");
        const csrfMatch=signedPage.body.match(
          /<script id="enrollment" type="application\/json">([^<]+)<\/script>/);
        assert.ok(csrfMatch,"Owner page must carry only a session-bound CSRF proof");
        const data=JSON.parse(csrfMatch[1]) as {csrf:string};
        assert.match(data.csrf,/^[A-Za-z0-9_-]{43}$/);
        assert.equal((await db.query<{n:number}>(
          "SELECT count(*)::integer AS n FROM owner_read_passkeys"
        )).rows[0]?.n,0,"Page load must not create a credential");
        const startedRegistration=await httpsStatus(port,ca,
          "/owner-passkey/register/begin",signedCookie,
          JSON.stringify({csrf:data.csrf,ownerSub:"attacker",requestId:"attacker"}));
        assert.equal(startedRegistration.status,200);
        const startedPayload=JSON.parse(startedRegistration.body) as {
          requestId:string;options:{challenge:string}
        };
        assert.match(startedPayload.requestId,/^[0-9a-f-]{36}$/);
        assert.match(startedPayload.options.challenge,/^[A-Za-z0-9_-]{43}$/);
        assert.equal((await db.query<{n:number}>(
          "SELECT count(*)::integer AS n FROM owner_read_passkey_registrations"
        )).rows[0]?.n,1,"Only a one-use registration challenge was created");
        assert.equal((await db.query<{n:number}>(
          "SELECT count(*)::integer AS n FROM owner_read_passkeys"
        )).rows[0]?.n,0,"An unused registration challenge cannot enroll a passkey");

        // Exercise the REAL compiled HTTPS acceptance listener with Chrome's
        // WebAuthn API. The authenticator is VIRTUAL and the fixture owner
        // session is synthetic; this is not physical user acceptance.
        browser=await chromium.launch({channel:"chrome",headless:true,
          args:["--no-proxy-server"]});
        const context=await browser.newContext({ignoreHTTPSErrors:true});
        try{
          const encoded=encodeURIComponent(token+"."+
            createHmac("sha256",authSecret).update(token).digest("base64"));
          await context.addCookies([{
            url:origin,name:"__Secure-better-auth.session_token",
            value:encoded,secure:true,httpOnly:true,sameSite:"Lax"
          }]);
          const page=await context.newPage();
          const devtools=await context.newCDPSession(page);
          await devtools.send("WebAuthn.enable");
          await devtools.send("WebAuthn.addVirtualAuthenticator",{options:{
            protocol:"ctap2",transport:"internal",hasResidentKey:true,
            hasUserVerification:true,isUserVerified:true,
            automaticPresenceSimulation:true
          }});
          const opened=await page.goto(origin+"/owner-passkey/register");
          assert.equal(opened?.status(),200,
            "Actual Chrome owner navigation requires signed first-party session");
          assert.equal((await db.query<{n:number}>(
            "SELECT count(*)::integer AS n FROM owner_read_passkeys"
          )).rows[0]?.n,0,"Page load must never silently register");
          await page.getByRole("button",{name:"Register passkey"}).click();
          await page.getByText(/registered but not activated/i)
            .waitFor({timeout:20_000});
          const created=await db.query<{owner_sub:string;enabled:boolean}>(
            "SELECT owner_sub,enabled FROM owner_read_passkeys");
          assert.equal(created.rowCount,1);
          assert.equal(created.rows[0]?.owner_sub,owner);
          assert.equal(created.rows[0]?.enabled,false,
            "Successful virtual WebAuthn registration must remain inactive");
        }finally{await context.close();}
        assert.equal((await db.query<{n:number}>(
          "SELECT count(*)::integer AS n FROM owner_read_approvals"
        )).rows[0]?.n,0,"No project approval can result from enrollment");
        await db.query('DELETE FROM "session" WHERE "id"=$1',[sessionId]);
        assert.equal((await httpsStatus(
          port,ca,"/owner-passkey/register",signedCookie)).status,403);
        assert.equal((await httpsStatus(port,ca,
          "/owner-passkey/register/begin",signedCookie,
          JSON.stringify({csrf:data.csrf}))).status,403,
          "Revoked owner sessions cannot reuse previously issued CSRF tokens");
      }finally{
        await browser?.close();
        if(proc&&!proc.killed){
          proc.kill("SIGTERM");
          await Promise.race([
            new Promise<void>(resolve=>proc!.once("exit",()=>resolve())),
            new Promise<void>(resolve=>setTimeout(resolve,1500))
          ]);
          if(proc.exitCode===null)proc.kill("SIGKILL");
        }
        await rm(tmp,{recursive:true,force:true});
        if(regCreated){
          await db.query("DROP OWNED BY cloud_cli_owner_reg");
          await db.query("DROP ROLE cloud_cli_owner_reg");
        }
        if(idCreated){
          await db.query("DROP OWNED BY cloud_cli_owner_id");
          await db.query("DROP ROLE cloud_cli_owner_id");
        }
      }
    });
  });
