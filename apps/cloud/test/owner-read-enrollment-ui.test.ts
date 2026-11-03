import assert from "node:assert/strict";
import {execFileSync} from "node:child_process";
import {mkdtemp,readFile,rm} from "node:fs/promises";
import {createServer,type Server} from "node:https";
import {tmpdir} from "node:os";
import path from "node:path";
import {test} from "node:test";
import {chromium} from "playwright";
import {generateRegistrationOptions,verifyRegistrationResponse,
  type RegistrationResponseJSON} from "@simplewebauthn/server";
import {createOwnerPasskeyEnrollmentPageHandler,renderOwnerPasskeyEnrollment}
  from "../src/owner-read-enrollment-ui.js";

test("enrollment HTML requires verified owner context and escapes untrusted names",()=>{
  assert.throws(()=>renderOwnerPasskeyEnrollment("owner","short"));
  const html=renderOwnerPasskeyEnrollment(
    "<script>alert(1)</script>","synthetic_owner_csrf_abcdefgh0123456");
  assert.match(html,/&lt;script&gt;alert\(1\)&lt;\/script&gt;/);
  assert.ok(!html.includes("<script>alert(1)</script>"));
  assert.match(html,/Registration does not activate/);
  assert.match(html,/owner-passkey\/register\/client.js/);
});

test("Chrome HTTPS passkey enrollment is click-only, session-gated and produces inactive result",
  {timeout:75_000},async()=>{
  const root=await mkdtemp(path.join(tmpdir(),"cloud-passkey-enroll-ui-"));
  let server:Server|undefined;
  let browser:Awaited<ReturnType<typeof chromium.launch>>|undefined;
  try{
    const key=path.join(root,"key.pem"),cert=path.join(root,"cert.pem");
    execFileSync("openssl",[
      "req","-x509","-newkey","rsa:2048","-sha256","-nodes","-days","1",
      "-keyout",key,"-out",cert,"-subj","/CN=localhost",
      "-addext","subjectAltName=DNS:localhost"
    ],{stdio:"ignore"});
    const script=await readFile(new URL("../src/owner-read-enrollment-client.js",
      import.meta.url));
    const owner="verified-owner",csrf="synthetic_csrf_0123456789abcdef";
    let origin="";
    let issued:Awaited<ReturnType<typeof generateRegistrationOptions>>|null=null;
    let registered=0,requests=0,consented=false;
    const session=async(request:{headers:{cookie?:string}})=>
      request.headers.cookie==="enrollment-fixture=synthetic"?
        {ownerSub:owner,csrf}:null;
    let pageHandler:ReturnType<typeof createOwnerPasskeyEnrollmentPageHandler>;
    server=createServer({key:await readFile(key),cert:await readFile(cert)},
      (request,response)=>{void (async()=>{
        if(request.url==="/owner-passkey/register/client.js"){
          response.writeHead(200,{"Content-Type":"text/javascript"});
          response.end(script);return;
        }
        if(request.url==="/owner-passkey/register"){
          await pageHandler(request,response);return;
        }
        if(!await session(request)||request.method!=="POST"||
          request.headers.origin!==origin||
          request.headers["content-type"]!=="application/json"){
          response.writeHead(403);response.end();return;
        }
        const chunks:Buffer[]=[];
        for await(const chunk of request)chunks.push(Buffer.from(chunk));
        const body=JSON.parse(Buffer.concat(chunks).toString("utf8")) as {
          csrf:string;requestId?:string;response?:RegistrationResponseJSON
        };
        if(body.csrf!==csrf){response.writeHead(403);response.end();return;}
        if(request.url==="/owner-passkey/register/begin"){
          requests++;
          issued=await generateRegistrationOptions({
            rpName:"KiCad Cloud",rpID:"localhost",userName:owner,
            userID:Uint8Array.from(Buffer.alloc(32,8)),
            authenticatorSelection:{userVerification:"required"},
            supportedAlgorithmIDs:[-7]
          });
          response.writeHead(200,{"Content-Type":"application/json"});
          response.end(JSON.stringify({requestId:"synthetic-enrollment",options:issued}));
          return;
        }
        if(request.url==="/owner-passkey/register/complete"&&issued&&
          body.requestId==="synthetic-enrollment"&&registered===0&&body.response){
          const verdict=await verifyRegistrationResponse({
            response:body.response,expectedChallenge:issued.challenge,
            expectedOrigin:origin,expectedRPID:"localhost",
            requireUserVerification:true,supportedAlgorithmIDs:[-7]
          });
          if(verdict.verified&&verdict.registrationInfo.userVerified){
            registered++;consented=true;
            response.writeHead(201,{"Content-Type":"application/json"});
            response.end(JSON.stringify({state:"registered_inactive"}));return;
          }
        }
        response.writeHead(403);response.end();
      })().catch(()=>{if(!response.headersSent)response.writeHead(403);
        response.end();});});
    await new Promise<void>(resolve=>server!.listen(0,"::",resolve));
    const address=server.address();
    assert.ok(address&&typeof address!=="string");
    origin="https://localhost:"+address.port;
    pageHandler=createOwnerPasskeyEnrollmentPageHandler(origin,session);
    browser=await chromium.launch({channel:"chrome",headless:true});
    const ctx=await browser.newContext({ignoreHTTPSErrors:true});
    try{
      const denied=await ctx.request.get(origin+"/owner-passkey/register");
      assert.equal(denied.status(),403);
      await ctx.addCookies([{url:origin,name:"enrollment-fixture",
        value:"synthetic",secure:true,httpOnly:true,sameSite:"Strict"}]);
      const page=await ctx.newPage();
      const cdp=await ctx.newCDPSession(page);
      await cdp.send("WebAuthn.enable");
      await cdp.send("WebAuthn.addVirtualAuthenticator",{options:{
        protocol:"ctap2",transport:"internal",hasResidentKey:true,
        hasUserVerification:true,isUserVerified:true,
        automaticPresenceSimulation:true
      }});
      const loaded=await page.goto(origin+"/owner-passkey/register");
      assert.equal(loaded?.status(),200);
      assert.equal(loaded?.headers()["cache-control"],"no-store");
      assert.equal(await page.locator("#owner").textContent(),owner);
      assert.equal(await page.locator("#status").textContent(),"Not registered.");
      await page.waitForTimeout(150);
      assert.equal(requests,0,"Opening review never issues challenge");
      assert.equal(registered,0);
      await page.getByRole("button",{name:"Register passkey"}).click();
      await page.getByText(/Passkey registered but not activated/i)
        .waitFor({timeout:25_000});
      assert.equal(requests,1);
      assert.equal(registered,1);
      assert.equal(consented,true,"Server verified real WebAuthn UV signature");
      assert.equal(await page.locator("#register").isDisabled(),true);
    }finally{await ctx.close();}
  }finally{
    await browser?.close();
    if(server)await new Promise<void>(resolve=>server!.close(()=>resolve()));
    await rm(root,{recursive:true,force:true});
  }
});
