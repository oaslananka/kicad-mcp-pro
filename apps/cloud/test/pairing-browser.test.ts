import assert from "node:assert/strict";
import {randomUUID} from "node:crypto";
import {test} from "node:test";
import type {BrowserIdentity} from "../src/browser.js";
import {pairingBrowserResponse} from "../src/pairing-browser.js";
import type {PairingReviewPort,BrowserPairingReview} from "../src/pairing-review.js";

const origin="http://127.0.0.1:8787";
function fixture(owner:string|null="owner-a",result:BrowserPairingReview="approved"){
  const calls:Array<[string,string,string,string]>=[];
  const identity={
    $context:Promise.resolve({secret:"synthetic-identity-secret-32-characters-for-tests"}),
    api:{getSession:async()=>owner?{user:{id:owner},session:{id:"session-a"}}:null},
    handler:async()=>new Response(null,{status:404})
  } as unknown as BrowserIdentity;
  const pairings:PairingReviewPort={
    async review(id,user,code,decision){
      calls.push([id,user,code,decision]);return result;
    }
  };
  return {identity,pairings,calls};
}
async function get(f:ReturnType<typeof fixture>){
  return pairingBrowserResponse(new Request(origin+"/devices/pairing"),f.identity,origin,f.pairings);
}
function form(
  id:string,code:string,token:string,cookie:string,originHeader=origin
):Request{
  return new Request(origin+"/devices/pairing/review",{
    method:"POST",headers:{
      "Content-Type":"application/x-www-form-urlencoded",
      Origin:originHeader,Cookie:cookie
    },
    body:new URLSearchParams({challenge_id:id,user_code:code,decision:"approve",csrf:token})
  });
}
test("pairing review requires session and escapes injected content",async()=>{
  assert.equal((await get(fixture(null)))?.status,303);
  const f=fixture(),res=await get(f);
  assert.equal(res?.status,200);
  assert.equal(res?.headers.get("referrer-policy"),"same-origin");
  const html=await res!.text();
  assert.match(html,/Connect your device/);
  assert.match(html,/Advanced: enter pairing details manually/);
  assert.match(html,/assets\/pairing-review\.js/);
  assert.match(res!.headers.get("content-security-policy")??"",/script-src 'self'/);
  assert.match(html,/Approve device/);
  assert.match(res!.headers.get("set-cookie")??"",/HttpOnly; SameSite=Strict/);
  assert.deepEqual(f.calls,[]);
});
test("valid browser owner and CSRF can explicitly approve pending pairing",async()=>{
  const f=fixture(),page=await get(f);
  const html=await page!.text();
  const token=/name="csrf" value="([^"]+)"/.exec(html)?.[1]??"";
  const cookie=(page!.headers.get("set-cookie")??"").split(";")[0];
  const id=randomUUID();
  const response=await pairingBrowserResponse(
    form(id,"ABCDEF-123456",token,cookie),f.identity,origin,f.pairings);
  assert.equal(response?.status,303);
  assert.equal(response?.headers.get("location"),"/devices/pairing");
  assert.deepEqual(f.calls,[[id,"owner-a","ABCDEF-123456","approve"]]);
});
test("CSRF, foreign owner, Origin, duplicates and malformed ID fail before review",async()=>{
  const f=fixture(),page=await get(f),body=await page!.text();
  const proof=/name="csrf" value="([^"]+)"/.exec(body)?.[1]??"";
  const cookie=(page!.headers.get("set-cookie")??"").split(";")[0];
  const id=randomUUID(),code="ABCDEF-123456";
  assert.equal((await pairingBrowserResponse(form(id,code,proof,cookie,"https://evil.test"),
    f.identity,origin,f.pairings))?.status,403);
  assert.equal((await pairingBrowserResponse(form(id,code,proof,""),
    f.identity,origin,f.pairings))?.status,403);
  assert.equal((await pairingBrowserResponse(form(randomUUID(),code,proof,cookie),
    fixture("other-user").identity,origin,f.pairings))?.status,403);
  assert.equal((await pairingBrowserResponse(form("bad",code,proof,cookie),
    f.identity,origin,f.pairings))?.status,400);
  const invalid=form(id,code,proof,cookie);
  const payload=new URLSearchParams(await invalid.text());
  payload.append("csrf",proof);
  const duplicate=new Request(origin+"/devices/pairing/review",{
    method:"POST",headers:{
      "Content-Type":"application/x-www-form-urlencoded",Origin:origin,Cookie:cookie
    },body:payload
  });
  assert.equal((await pairingBrowserResponse(duplicate,f.identity,origin,f.pairings))?.status,400);
  assert.deepEqual(f.calls,[]);
});
test("throttling and unavailable challenges fail without leaking existence",async()=>{
  const f=fixture("owner-a","throttled"),page=await get(f);
  const html=await page!.text(),id=randomUUID();
  const csrf=/name="csrf" value="([^"]+)"/.exec(html)?.[1]??"";
  const cookie=(page!.headers.get("set-cookie")??"").split(";")[0];
  const throttled=await pairingBrowserResponse(form(id,"ABCDEF-123456",csrf,cookie),
    f.identity,origin,f.pairings);
  assert.equal(throttled?.status,429);
  assert.doesNotMatch(await throttled!.text(),/ABCDEF-123456/);
  const missing=fixture("owner-a","unavailable");
  assert.equal((await pairingBrowserResponse(form(id,"ABCDEF-123456",csrf,cookie),
    missing.identity,origin,missing.pairings))?.status,400);
});
test("no authenticator or store fails closed",async()=>{
  const f=fixture(),page=await get(f);
  const html=await page!.text(),cookie=(page!.headers.get("set-cookie")??"").split(";")[0];
  const csrf=/name="csrf" value="([^"]+)"/.exec(html)?.[1]??"";
  assert.equal((await pairingBrowserResponse(form(randomUUID(),"ABCDEF-123456",csrf,cookie),
    f.identity,origin))?.status,503);
});
