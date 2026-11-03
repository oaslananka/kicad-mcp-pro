import assert from "node:assert/strict";
import {randomBytes,randomUUID} from "node:crypto";
import {mkdtemp,readFile,rm} from "node:fs/promises";
import {tmpdir} from "node:os";
import path from "node:path";
import {execFileSync} from "node:child_process";
import {createServer} from "node:https";
import {test} from "node:test";
import type {Server} from "node:https";
import {chromium} from "playwright";
import {generateRegistrationOptions,generateAuthenticationOptions,
  verifyRegistrationResponse,verifyAuthenticationResponse,
  type RegistrationResponseJSON,type AuthenticationResponseJSON,
  type WebAuthnCredential} from "@simplewebauthn/server";
import {renderOwnerReadReview,ownerReadReviewHeaders}
  from "../src/owner-read-approval-ui.js";

const fixture=()=>({
  requestId:randomUUID(),ownerSub:"owner:<script>alert(1)</script>",
  clientId:"A<svg/onload=alert(1)>B",deviceId:randomUUID(),
  projectId:randomUUID(),origin:"https://cloud.example.test",
  expiresAtUnixMs:Date.now()+25_000
});
const challenge=()=>randomBytes(32).toString("base64url");

test("review page shows exact scope, escapes injection and rejects non-UV/mismatched actors",
  ()=>{
    const csrf="A".repeat(43);
    const intent=fixture(),options={
      challenge:challenge(),rpId:"localhost",userVerification:"required" as const
    };
    const html=renderOwnerReadReview({intent,options},intent.ownerSub,
      "https://localhost:4443",csrf);
    assert.match(html,/Approve one project summary/);
    assert.match(html,/project_summary \(presence flags only\)/);
    assert.ok(html.includes("A&lt;svg/onload=alert(1)&gt;B"));
    assert.ok(!html.includes("<script>alert(1)</script>"));
    assert.match(html,/owner-read\/review.js/);
    assert.match(html,/No board contents/);
    assert.ok(!html.includes("onerror="));
    assert.equal(ownerReadReviewHeaders["Cache-Control"],"no-store");
    assert.match(ownerReadReviewHeaders["Content-Security-Policy"],/script-src 'self'/);
    assert.throws(()=>renderOwnerReadReview({intent,options},"other-owner","https://localhost:4443",csrf));
    assert.throws(()=>renderOwnerReadReview({intent,options:{
      ...options,userVerification:"preferred" as const}},intent.ownerSub,"https://localhost:4443",csrf));
    assert.throws(()=>renderOwnerReadReview({intent,options:{
      ...options,rpId:"untrusted.example"}},intent.ownerSub,"https://localhost:4443",csrf));
    assert.throws(()=>renderOwnerReadReview({intent:{
      ...intent,origin:"http://cloud.example.test"},options},intent.ownerSub,"https://localhost:4443",csrf));
    assert.throws(()=>renderOwnerReadReview({intent:{
      ...intent,expiresAtUnixMs:Date.now()-1},options},intent.ownerSub,"https://localhost:4443",csrf));
  });

test("Chrome virtual WebAuthn requires deliberate click, verifies UV assertion, denies cancellation",
  {timeout:100_000},async()=>{
    const dir=await mkdtemp(path.join(tmpdir(),"cloud-passkey-ui-"));
    let server:Server|undefined;
    const script=await readFile(new URL("../src/owner-read-review-client.js",import.meta.url));
    let browser:Awaited<ReturnType<typeof chromium.launch>>|undefined;
    try{
      const key=path.join(dir,"key.pem"),cert=path.join(dir,"cert.pem");
      execFileSync("openssl",["req","-x509","-newkey","rsa:2048","-sha256",
        "-nodes","-days","1","-keyout",key,"-out",cert,"-subj","/CN=localhost",
        "-addext","subjectAltName=DNS:localhost"],{stdio:"ignore"});
      let html="<h1>Setup</h1>";
      let expectedOrigin="";
      let userCredential:WebAuthnCredential|undefined;
      let expectedChallenge="";
      let approved=0;
      let lastScope="";
      server=createServer({
        key:await readFile(key),cert:await readFile(cert)
      },async(req,res)=>{
        try{
          if(req.url==="/owner-read/review.js"){
            res.writeHead(200,{"Content-Type":"text/javascript; charset=utf-8",
              "Cache-Control":"no-store"});res.end(script);return;
          }
          if(req.url==="/owner-read/approval"&&req.method==="POST"){
            const chunks:Buffer[]=[];
            for await(const chunk of req)chunks.push(Buffer.from(chunk));
            const payload=JSON.parse(Buffer.concat(chunks).toString("utf8")) as {
              requestId:string;challenge:string;assertion:AuthenticationResponseJSON;
            };
            if(!userCredential||payload.challenge!==expectedChallenge||
               payload.requestId!==lastScope||approved!==0){
              res.writeHead(403);res.end();return;
            }
            const checked=await verifyAuthenticationResponse({
              response:payload.assertion,expectedChallenge,expectedOrigin,
              expectedRPID:"localhost",credential:userCredential,
              requireUserVerification:true
            });
            if(!checked.verified||!checked.authenticationInfo.userVerified){
              res.writeHead(403);res.end();return;
            }
            approved++;
            res.writeHead(204);res.end();return;
          }
          if(req.url==="/setup"||req.url==="/"){
            res.writeHead(200,req.url==="/setup"?{"Content-Type":"text/html"}:
              {...ownerReadReviewHeaders});res.end(req.url==="/setup"?
              "<!doctype html><html><body>Passkey fixture</body></html>":html);return;
          }
          res.writeHead(404);res.end();
        }catch{res.writeHead(403);res.end();}
      });
      await new Promise<void>(resolve=>server!.listen(0,"::",resolve));
      const address=server.address();
      assert.ok(address&&typeof address!=="string");
      expectedOrigin="https://localhost:"+address.port;
      // GitHub ubuntu-latest and the owner test devices have system Chrome.
      // Avoid downloading a second Playwright browser into CI or test hosts.
      browser=await chromium.launch({channel:"chrome",headless:true});
      const context=await browser.newContext({ignoreHTTPSErrors:true});
      const page=await context.newPage();
      const cdp=await context.newCDPSession(page);
      await cdp.send("WebAuthn.enable");
      await cdp.send("WebAuthn.addVirtualAuthenticator",{options:{
        protocol:"ctap2",transport:"internal",hasResidentKey:true,
        hasUserVerification:true,isUserVerified:true,automaticPresenceSimulation:true
      }});
      const registration=await generateRegistrationOptions({
        rpName:"KiCad Cloud isolated fixture",rpID:"localhost",
        userName:"synthetic-owner",userID:randomBytes(32),
        authenticatorSelection:{residentKey:"preferred",userVerification:"required"}
      });
      await page.goto(expectedOrigin+"/setup");
      const enrollment=await page.evaluate(`(async () => {
        const opts = ${JSON.stringify(registration)};
        const decode = (value) => Uint8Array.from(
          atob(value.replace(/-/g,"+").replace(/_/g,"/") +
            "=".repeat((4-value.length%4)%4)),c=>c.charCodeAt(0));
        const created=await navigator.credentials.create({publicKey:{
          ...opts,challenge:decode(opts.challenge),
          user:{...opts.user,id:decode(opts.user.id)},
          excludeCredentials:[]
        }});
        if(!created || typeof created.toJSON!=="function")
          throw Error("WebAuthn registration JSON unavailable");
        return created.toJSON();
      })()`) as RegistrationResponseJSON;
      const verified=await verifyRegistrationResponse({
        response:enrollment,expectedChallenge:registration.challenge,
        expectedOrigin,expectedRPID:"localhost",requireUserVerification:true
      });
      assert.equal(verified.verified,true);
      if(!verified.verified)throw Error("registration failure");
      userCredential=verified.registrationInfo.credential;
      const assertionOptions=await generateAuthenticationOptions({
        rpID:"localhost",userVerification:"required",timeout:20_000,
        allowCredentials:[{id:userCredential.id}]
      });
      expectedChallenge=assertionOptions.challenge;
      const intent={
        ...fixture(),ownerSub:"test-owner",clientId:"test-oauth-client",
        origin:"https://cloud.example.test",expiresAtUnixMs:Date.now()+20_000
      };
      lastScope=intent.requestId;
      html=renderOwnerReadReview({intent,options:assertionOptions},intent.ownerSub,
        expectedOrigin,"A".repeat(43));
      await page.goto(expectedOrigin+"/");
      assert.equal(await page.locator("#status").textContent(),"Not approved.");
      await page.waitForTimeout(200);
      assert.equal(approved,0,"opening the page must not silently approve");
      assert.equal(await page.locator("#project").textContent(),intent.projectId);
      assert.equal(await page.locator("#client").textContent(),intent.clientId);
      assert.equal(await page.locator("#origin").textContent(),intent.origin);
      assert.equal(await page.locator("#authority").textContent(),expectedOrigin);
      await page.getByRole("button",{name:/verify passkey/i}).click();
      await page.getByText("Passkey accepted. Approval submitted.").waitFor();
      assert.equal(approved,1,"explicit button triggers exactly one real signed assertion");
      await page.reload();
      await page.getByRole("button",{name:"Deny"}).click();
      assert.equal(await page.locator("#status").textContent(),
        "Request denied. No approval was sent.");
      assert.equal(await page.getByRole("button",{name:/verify passkey/i}).isDisabled(),
        true);
      assert.equal(approved,1,"denial must not call issuer");
      await context.close();
    }finally{
      await browser?.close();
      if(server)await new Promise<void>(resolve=>server!.close(()=>resolve()));
      await rm(dir,{recursive:true,force:true});
    }
  });
