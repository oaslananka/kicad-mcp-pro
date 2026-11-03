import assert from "node:assert/strict";
import {test} from "node:test";
import {makeSignature} from "better-auth/crypto";
import {consentResponse} from "../src/consent.js";
import type {BrowserIdentity} from "../src/browser.js";

const origin="http://127.0.0.1:8787";
const secret="test-secret-for-signing-mcp-consent-query";
const user={id:"user-one",name:"Owner"};
const calls:{path:string,body:unknown}[]=[];
async function signed(scopes="openid projects:read",clientId="chatgpt-mcp",expired=false,
  callback?:string):Promise<string> {
  const params=new URLSearchParams({
    client_id:clientId,
    scope:scopes,
    exp:String(Math.floor(Date.now()/1000)+(expired?-300:300))
  });
  if(callback)params.set("redirect_uri",callback);
  // Signed OAuth fields are canonically sorted by Better Auth.
  params.sort();
  const signature=await makeSignature(params.toString(),secret);
  params.append("sig",signature);
  return params.toString();
}
function identity(options:{user?:false,client?:false,badRedirect?:true}={}):BrowserIdentity {
  return {
    $context:Promise.resolve({secret}) as BrowserIdentity["$context"],
    api:{getSession:async()=>options.user===false?null:{user}} as BrowserIdentity["api"],
    handler:async(request:Request)=>{
      const url=new URL(request.url);
      calls.push({path:url.pathname,body:request.method==="POST"?await request.json():null});
      if(url.pathname==="/api/auth/oauth2/public-client") {
        return Response.json(options.client===false?{error:"not_found"}:{
          client_id:url.searchParams.get("client_id"),client_name:'Client <script>alert(1)</script>'
        },{status:options.client===false?404:200});
      }
      if(url.pathname==="/api/auth/oauth2/consent") {
        return Response.json({redirect:true,url:options.badRedirect?"javascript:alert(1)":"https://chatgpt.com/connector/oauth/done"},
          {headers:{"Set-Cookie":"provider-state=verified; HttpOnly; Path=/; SameSite=Lax"}});
      }
      return Response.json({error:"not_found"},{status:404});
    }
  };
}
function get(query:string, cookie=""):Request {
  return new Request(origin+"/consent?"+query,{headers:cookie?{Cookie:cookie}:{}});
}
function post(query:string,csrf:string,cookie:string,decision:string,requestOrigin=origin):Request {
  return new Request(origin+"/consent",{method:"POST",
    headers:{"Content-Type":"application/x-www-form-urlencoded","Origin":requestOrigin,"Cookie":cookie},
    body:new URLSearchParams({oauth_query:query,csrf,decision})
  });
}
function tokenFrom(body:string):string {
  return /name="csrf" value="([^"]+)"/.exec(body)?.[1]??"";
}
test("consent displays full signed scope with verified session, client and escaped name",async()=>{
  calls.length=0;
  const query=await signed();
  const reply=await consentResponse(get(query),identity(),origin);
  assert.equal(reply?.status,200);
  const body=await reply!.text();
  assert.match(body,/projects:read/);
  assert.match(body,/&lt;script&gt;/);
  assert.equal(body.toLowerCase().includes("<script"),false);
  assert.match(reply!.headers.get("set-cookie")??"",/HttpOnly/);
  assert.match(reply!.headers.get("set-cookie")??"",/SameSite=Strict/);
  assert.equal(calls.filter(c=>c.path.includes("consent")).length,0);
});
test("native browser consent allows only the signed client callback and retains strict Origin",async()=>{
  const callback="https://chatgpt.com/connector_platform_oauth_redirect";
  const query=await signed("openid profile offline_access projects:read","https://chatgpt.com/oauth/client.json",false,callback);
  const response=await consentResponse(get(query),identity(),origin);
  assert.equal(response?.status,200);
  assert.equal(response?.headers.get("referrer-policy"),"same-origin");
  const csp=response?.headers.get("content-security-policy")??"";
  assert.match(csp,/form-action 'self' https:\/\/chatgpt\.com;/);
  assert.doesNotMatch(csp,/https:\/\/evil\.invalid/);
  const tampered=query.replace(encodeURIComponent(callback),encodeURIComponent("https://evil.invalid/steal"));
  assert.equal((await consentResponse(get(tampered),identity(),origin))?.status,403);
  const other=await signed("openid projects:read","chatgpt-mcp",false,"javascript:alert(1)");
  const disallowed=await consentResponse(get(other),identity(),origin);
  assert.equal(disallowed?.status,200);
  assert.doesNotMatch(disallowed?.headers.get("content-security-policy")??"",/javascript:/);
});

test("invalid, expired or expanded scope query is rejected before UI",async()=>{
  const original=await signed();
  assert.equal((await consentResponse(get(original.replace("projects%3Aread","projects%3Amanage")),identity(),origin))?.status,403);
  assert.equal((await consentResponse(get(await signed("openid projects:read","chatgpt-mcp",true)),identity(),origin))?.status,403);
  assert.equal((await consentResponse(get(await signed()),identity({client:false}),origin))?.status,403);
  const unmanaged=await signed("openid projects:manage");
  assert.equal((await consentResponse(get(unmanaged),identity(),origin))?.status,403);
  const management=await signed("openid projects:manage","trusted-portal");
  assert.equal((await consentResponse(get(management),identity(),origin,"trusted-portal"))?.status,200);
});
test("consent GET does not authorize without a session",async()=>{
  const response=await consentResponse(get(await signed()),identity({user:false}),origin);
  assert.equal(response?.status,303);
  assert.match(response!.headers.get("location")??"",/^\/sign-in\?/);
});
test("CSRF, cross-origin, wrong session, or tampered query cannot approve",async()=>{
  const query=await signed();
  const auth=identity();
  const view=await consentResponse(get(query),auth,origin);
  const csrf=tokenFrom(await view!.text());
  const cookie=(view!.headers.get("set-cookie")??"").split(";")[0];
  calls.length=0;
  assert.equal((await consentResponse(post(query,csrf,cookie,"approve","https://evil.invalid"),auth,origin))?.status,403);
  assert.equal((await consentResponse(post(query,csrf,"","approve"),auth,origin))?.status,403);
  assert.equal((await consentResponse(post(query,csrf,cookie,"execute"),auth,origin))?.status,400);
  assert.equal((await consentResponse(post(query,csrf,cookie,"approve"),identity({user:false}),origin))?.status,401);
  const another=await signed("profile projects:read");
  assert.equal((await consentResponse(post(another,csrf,cookie,"approve"),auth,origin))?.status,403);
  assert.equal(calls.some(c=>c.path.endsWith("/consent")),false);
});
test("explicit approval and denial call official provider, never issue credentials in Cloud",async()=>{
  const query=await signed();
  const auth=identity();
  const view=await consentResponse(get(query),auth,origin);
  const csrf=tokenFrom(await view!.text());
  const cookie=(view!.headers.get("set-cookie")??"").split(";")[0];
  calls.length=0;
  for(const [decision,accept] of [["approve",true],["deny",false]] as const){
    const reply=await consentResponse(post(query,csrf,cookie,decision),auth,origin);
    assert.equal(reply?.status,303);
    assert.equal(reply?.headers.get("location"),"https://chatgpt.com/connector/oauth/done");
    assert.equal((calls.at(-1)?.body as {accept:boolean})?.accept,accept);
  }
  const bad=await consentResponse(post(query,csrf,cookie,"approve"),identity({badRedirect:true}),origin);
  assert.equal(bad?.status,502);
});
