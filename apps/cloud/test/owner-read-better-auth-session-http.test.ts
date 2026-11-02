import assert from "node:assert/strict";
import {createHmac,randomBytes,randomUUID} from "node:crypto";
import {execFileSync} from "node:child_process";
import {mkdtemp,readFile,rm} from "node:fs/promises";
import type {Server} from "node:https";
import {request as httpsRequest} from "node:https";
import {tmpdir} from "node:os";
import path from "node:path";
import {test} from "node:test";
import {createIdentity} from "../src/identity.js";
import {createIndependentOwnerSessionVerifier}
  from "../src/owner-read-better-auth-session.js";
import {createOwnerAcceptanceServer}
  from "../src/owner-acceptance-server.js";
import type {PgOwnerReadPasskeyRegistration}
  from "../src/owner-read-passkey-registration.js";
import {inIsolatedDatabase} from "./isolated-db.js";

const url=process.env.TEST_DATABASE_URL;
const authority="https://localhost";
test("real Better Auth session gates standalone HTTPS owner page and registration POST",
  {skip:!url,timeout:40_000},async()=>{
    await inIsolatedDatabase(url!,["003_better_auth.pgsql"],async db=>{
      const tmp=await mkdtemp(path.join(tmpdir(),"cloud-owner-session-http-"));
      let server:Server|undefined;
      try{
        const cert=path.join(tmp,"cert.pem");
        const key=path.join(tmp,"key.pem");
        execFileSync("openssl",["req","-x509","-newkey","rsa:2048",
          "-sha256","-nodes","-days","1","-keyout",key,"-out",cert,
          "-subj","/CN=localhost","-addext","subjectAltName=DNS:localhost"],
        {stdio:"ignore"});
        const secret=randomBytes(48).toString("hex");
        const owner="approved-owner",sessionId=randomUUID();
        const token=randomBytes(32).toString("base64url");
        const now=new Date(),expiry=new Date(Date.now()+20*60_000);
        await db.query('INSERT INTO "users"'+
          '("id","name","email","emailVerified") VALUES($1,$2,$3,true)',
          [owner,"Account owner","owner@test.invalid"]);
        await db.query('INSERT INTO "session"'+
          '("id","expiresAt","token","updatedAt","userId")'+
          ' VALUES($1,$2,$3,$4,$5)',[sessionId,expiry,token,now,owner]);
        const cookie="__Secure-better-auth.session_token="+
          encodeURIComponent(token+"."+
            createHmac("sha256",secret).update(token).digest("base64"));
        const identity=createIdentity({
          publicOrigin:authority,audience:authority+"/mcp",databaseUrl:url!
        },{secret,googleId:"",googleSecret:"",
          githubId:"synthetic-provider-id",githubSecret:"synthetic-provider-secret"},db);
        const verify=createIndependentOwnerSessionVerifier(
          identity,authority,owner,randomBytes(48));
        let begins=0;
        const mock={
          begin:async(identitySub:string,requestId:string)=>{
            assert.equal(identitySub,owner);
            assert.match(requestId,/^[0-9a-f-]{36}$/);
            begins++;
            return {challenge:"A".repeat(43),
              rp:{name:"KiCad",id:"localhost"}};
          },
          complete:async()=> "denied" as const
        } as unknown as PgOwnerReadPasskeyRegistration;
        server=createOwnerAcceptanceServer({
          authorityOrigin:authority,identity,sessionVerifier:verify,
          registration:mock,
          tls:{key:await readFile(key),cert:await readFile(cert)},
          clientScript:Buffer.from("/* owner browser script test fixture */".padEnd(130," "))
        });
        await new Promise<void>(resolve=>server!.listen(0,"127.0.0.1",resolve));
        const a=server.address();
        assert.ok(a&&typeof a!=="string");
        const port=a.port;
        const trustedCa=await readFile(cert);
        const invoke=(pathname:string,method:"GET"|"POST",
          cookieValue?:string,body?:object,override:Record<string,string>={})=>
          new Promise<{status:number;body:string}>((
            resolve,reject)=>{
            const req=httpsRequest({hostname:"127.0.0.1",port,
              servername:"localhost",ca:trustedCa,method,path:pathname,
              headers:{Host:"localhost",
                ...(cookieValue?{Cookie:cookieValue}:{}),
                ...(method==="POST"?{
                  Origin:authority,"Content-Type":"application/json",
                  "Sec-Fetch-Site":"same-origin"
                }:{}),...override}},res=>{
              const pieces:Buffer[]=[];
              res.on("data",(chunk:Buffer)=>pieces.push(Buffer.from(chunk)));
              res.on("end",()=>resolve({status:res.statusCode??0,
                body:Buffer.concat(pieces).toString("utf8")}));
              res.on("error",reject);
            });
            req.on("error",reject);
            req.end(body?JSON.stringify(body):undefined);
          });
        const health=await invoke("/health","GET");
        assert.equal(health.status,200);
        assert.deepEqual(JSON.parse(health.body),{
          status:"acceptance_only",registration:"inactive_only",
          activation:"disabled",approval:"disabled",connector:"disabled"
        });
        assert.equal((await invoke("/sign-in","GET")).status,200,
          "Existing Better Auth social login is reachable");
        assert.equal((await invoke("/owner-passkey/register/client.js","GET")).status,200);
        // Real Better Auth first-leg GitHub OAuth redirect: no provider
        // credentials, cookies or outbound GitHub request are leaked. The
        // test validates a genuine HTTPS form POST and its returned headers.
        const startGitHub=(origin:string)=>new Promise<{
          status:number;location:string;cookieCount:number;
          protectedStateCookie:boolean
        }>((resolve,reject)=>{
          const request=httpsRequest({
            hostname:"127.0.0.1",port,servername:"localhost",ca:trustedCa,
            method:"POST",path:"/auth/start/github",
            headers:{
              Host:"localhost",Origin:origin,
              "Content-Type":"application/x-www-form-urlencoded",
              "Sec-Fetch-Site":"same-origin"
            }
          },reply=>{
            // Do not retain, print or log cookie contents or OAuth state.
            const location=String(reply.headers.location??"");
            const raw=reply.headers["set-cookie"];
            const cookies=Array.isArray(raw)?raw:raw?[raw]:[];
            const cookieCount=cookies.length;
            const protectedStateCookie=cookies.some(value=>
              /(?:^|;\s*)HttpOnly(?:;|$)/i.test(value)&&
              /(?:^|;\s*)Secure(?:;|$)/i.test(value)&&
              /(?:^|;\s*)SameSite=Lax(?:;|$)/i.test(value)
            );
            reply.resume();
            reply.on("end",()=>resolve({
              status:reply.statusCode??0,location,cookieCount,
              protectedStateCookie
            }));
            reply.on("error",reject);
          });
          request.on("error",reject);
          request.end("oauth_query=");
        });
        const wrongOrigin=await startGitHub("https://attacker.example.test");
        assert.equal(wrongOrigin.status,403,
          "Cross-origin submission must never start social sign-in");
        const started=await startGitHub(authority);
        assert.equal(started.status,303,
          "Social sign-in must return a top-level browser redirect");
        const oauth=new URL(started.location);
        assert.equal(oauth.protocol,"https:");
        assert.equal(oauth.hostname,"github.com");
        assert.equal(oauth.pathname,"/login/oauth/authorize");
        assert.equal(oauth.searchParams.get("client_id"),
          "synthetic-provider-id");
        assert.equal(oauth.searchParams.get("redirect_uri"),
          authority+"/api/auth/callback/github",
          "GitHub must return to the independent owner authority");
        assert.ok(started.cookieCount>0,
          "State must be linked to a browser cookie");
        assert.equal(started.protectedStateCookie,true,
          "OAuth state cookie must be HttpOnly, Secure and SameSite=Lax");
        assert.equal((await invoke("/auth/start/github","GET")).status,303,
          "Direct GET must not start OAuth");

        assert.equal((await invoke("/owner-read/review.js","GET")).status,404,
          "Existing passive-only owner host must not serve review code");
        assert.equal((await invoke(
          "/owner-read/review?requestId="+randomUUID(),"GET",cookie)).status,404,
          "Passive-only owner host has no approval review route");
        assert.equal((await invoke("/internal/owner-read/intent","POST",
          undefined,{requestId:randomUUID()})).status,404,
          "Unsigned approval scope is not an entry point on the default host");
        assert.equal((await invoke("/owner-passkey/activate","GET")).status,404);
        assert.equal((await invoke("/api/auth/oauth2/token","GET")).status,404,
          "Owner acceptance service must not offer MCP token issuance");
        assert.equal((await invoke("/api/v1/connector/ws","GET")).status,404,
          "Owner acceptance service cannot expose connector sockets");
        assert.equal((await invoke("/owner-passkey/register","GET")).status,403);
        assert.equal((await invoke("/owner-passkey/register","GET",
          cookie,undefined,{Host:"spoofed.example.test"})).status,403);
        assert.equal((await invoke("/owner-passkey/register","GET",
          "better-auth.session_token=unsigned")).status,403);
        const opened=await invoke("/owner-passkey/register","GET",cookie);
        assert.equal(opened.status,200);
        assert.ok(opened.body.includes("Register passkey"));
        assert.equal(begins,0,"GET must not begin registration");
        const csrfMatch=opened.body.match(
          /<script id="enrollment" type="application\/json">([^<]+)<\/script>/);
        assert.ok(csrfMatch);
        const session=JSON.parse(csrfMatch[1]) as {csrf:string};
        assert.match(session.csrf,/^[A-Za-z0-9_-]{43}$/);
        const post=(csrf:string,override:Record<string,string>={})=>
          invoke("/owner-passkey/register/begin","POST",cookie,
            {csrf,ownerSub:"attacker",requestId:"attacker"},override);
        assert.equal((await post("wrong-proof")).status,403);
        assert.equal((await post(session.csrf,{
          Origin:"https://attacker.example.test"})).status,403);
        assert.equal((await post(session.csrf,{
          "Sec-Fetch-Site":"cross-site"})).status,403);
        assert.equal((await post(session.csrf,{
          "X-Forwarded-Host":"attacker.example.test"})).status,403);
        assert.equal(begins,0);
        const allowed=await post(session.csrf);
        assert.equal(allowed.status,200);
        const data=JSON.parse(allowed.body) as {requestId:string};
        assert.match(data.requestId,/^[0-9a-f-]{36}$/);
        assert.equal(begins,1,"Only real owner session starts enrollment");
        await db.query('DELETE FROM "session" WHERE "id"=$1',[sessionId]);
        assert.equal((await post(session.csrf)).status,403,
          "Revoked session cannot reuse previously displayed CSRF proof");
        assert.equal(begins,1);
      }finally{
        if(server)await new Promise<void>(r=>server!.close(()=>r()));
        await rm(tmp,{recursive:true,force:true});
      }
    });
  });
