import assert from "node:assert/strict";
import { test } from "node:test";
import { browserResponse, type BrowserIdentity } from "../src/browser.js";
import {createIdentity} from "../src/identity.js";
import {randomBytes} from "node:crypto";

const origin="http://127.0.0.1:8787";
function mock(url="https://github.com/login/oauth/authorize"):BrowserIdentity {
  return {
    handler:async (_request:Request) => new Response(JSON.stringify({url,redirect:true}),{
      status:200,headers:{"content-type":"application/json","set-cookie":"ba-state=opaque; Path=/; HttpOnly; SameSite=Lax"}
    })
  };
}
const form=(fields="oauth_query=") => new Request(origin+"/auth/start/github",{
  method:"POST",
  headers:{"Origin":origin,"Content-Type":"application/x-www-form-urlencoded"},
  body:fields
});

test("first-party sign-in is available only with builtin identity",async()=>{
  const page=await browserResponse(new Request(origin+"/sign-in"),mock(),origin);
  assert.equal(page?.status,200);
  assert.match(await page!.text(),/Continue with Google/);
  assert.equal(page?.headers.get("referrer-policy"),"same-origin",
    "Native browser form POST must not convert its Origin to null");
  assert.match(page?.headers.get("content-security-policy")??"",/form-action 'self' https:\/\/github\.com/,
    "Chrome must allow the GitHub OAuth redirect following first-party form POST");
  const invalid=await browserResponse(new Request(origin+"/sign-in?client_id=attacker"),mock(),origin);
  assert.equal(invalid?.status,400);
});

test("UTM-only chat referral strips tracking without weakening OAuth verification",async()=>{
  const referral=await browserResponse(
    new Request(origin+"/sign-in?utm_source=chatgpt.com"),mock(),origin);
  assert.equal(referral?.status,303);
  assert.equal(referral?.headers.get("location"),"/sign-in");
  assert.equal(referral?.headers.get("cache-control"),"no-store");

  for(const query of [
    "?utm_source=chatgpt.com&client_id=attacker",
    "?client_id=attacker&utm_source=chatgpt.com",
    "?utm_source=chatgpt.com&state=fake",
    "?utm_invalid=chatgpt.com",
    "?utm_source="+("x".repeat(1100))
  ]){
    const result=await browserResponse(new Request(origin+"/sign-in"+query),mock(),origin);
    assert.equal(result?.status,400,query.slice(0,100));
  }
});

test("GitHub-only identity hides and denies unconfigured Google login",async()=>{
  const identity=createIdentity({
    publicOrigin:origin,audience:origin+"/mcp",
    databaseUrl:"postgresql://127.0.0.1:65432/unused"
  },{
    secret:randomBytes(48).toString("hex"),
    googleId:"",googleSecret:"",
    githubId:"fixture-github-id",githubSecret:"fixture-github-secret"
  });
  const page=await browserResponse(new Request(origin+"/sign-in"),identity,origin);
  const text=await page!.text();
  assert.match(text,/Continue with GitHub/);
  assert.doesNotMatch(text,/Continue with Google/);
  const disallowed=await browserResponse(new Request(origin+"/auth/start/google",{
    method:"POST",
    headers:{Origin:origin,"Content-Type":"application/x-www-form-urlencoded"},
    body:"oauth_query="
  }),identity,origin);
  assert.equal(disallowed?.status,404);
});

test("direct OAuth start GET returns to first-party sign-in without starting OAuth",async()=>{
  const response=await browserResponse(new Request(origin+"/auth/start/github"),mock(),origin);
  assert.equal(response?.status,303);
  assert.equal(response?.headers.get("location"),"/sign-in");
  assert.equal(response?.headers.get("cache-control"),"no-store");
});

test("sign-in denies CSRF, tampered query, and extra fields",async()=>{
  const attack=await browserResponse(new Request(origin+"/auth/start/github",{
    method:"POST",
    headers:{"Origin":"https://untrusted.invalid","Content-Type":"application/x-www-form-urlencoded"},
    body:"oauth_query="
  }),mock(),origin);
  assert.equal(attack?.status,403);
  assert.equal((await browserResponse(form("oauth_query=x"),mock(),origin))?.status,400);
  assert.equal((await browserResponse(form("oauth_query=&callbackURL=https%3A%2F%2Fevil.example"),mock(),origin))?.status,400);
});

test("login redirect is allowlisted and carries only opaque Better Auth state",async()=>{
  const response=await browserResponse(form(),mock(),origin);
  assert.equal(response?.status,303);
  assert.equal(response?.headers.get("location"),"https://github.com/login/oauth/authorize");
  assert.match(response?.headers.get("set-cookie")??"",/HttpOnly/);
  const injected=await browserResponse(form(),mock("https://untrusted.invalid/login"),origin);
  assert.equal(injected?.status,502);
});

test("account page requires session; escaped account display has no HTML injection",async()=>{
  const absent=await browserResponse(new Request(origin+"/account"),mock(),origin);
  assert.equal(absent?.status,303);
  const user=mock() as BrowserIdentity & {api: any};
  user.api={getSession:async()=>({user:{name:"<script>alert(1)</script>"}})};
  const response=await browserResponse(new Request(origin+"/account"),user,origin);
  assert.equal(response?.status,200);
  const text=await response!.text();
  assert.equal(text.toLowerCase().includes("<script>alert(1)</script>"),false);
  assert.match(text,/pairing-login-continuation\.js/);
  assert.match(text,/&lt;script&gt;/);
  assert.match(response?.headers.get("content-security-policy")??"",/default-src 'none'/);
});

test("account linking is explicit, displays only enabled and linked providers",async()=>{
  const identity=mock() as BrowserIdentity & {api:any;options:any};
  identity.options={socialProviders:{google:{},github:{}}};
  identity.api={
    getSession:async()=>({user:{name:"Ada"}}),
    listUserAccounts:async()=>[{providerId:"google",id:"linked-google"}]
  };
  const account=await browserResponse(new Request(origin+"/account"),identity,origin);
  assert.equal(account?.status,200);
  const page=await account!.text();
  assert.match(page,/Google<\/strong> — Connected/);
  assert.match(page,/Connect GitHub to this account/);
  assert.doesNotMatch(page,/Connect Google to this account/);
  assert.match(page,/action="\/auth\/link\/github"/);
  assert.match(page,/Accounts are never merged automatically/);
  assert.doesNotMatch(page,/linked-google/,"Account identifiers must not leak to HTML");
});

test("linking requires an already signed in owner and rejects forged request data",async()=>{
  const identity=mock() as BrowserIdentity & {api:any};
  const calls:string[]=[];
  identity.handler=async req=>{calls.push(req.url);return new Response(JSON.stringify({
    url:"https://github.com/login/oauth/authorize",redirect:true
  }),{status:200,headers:{"content-type":"application/json"}})};
  identity.api={getSession:async()=>null};

  const request=(path:string,headers:Record<string,string>,body="")=>
    new Request(origin+path,{method:"POST",headers,body});
  const formHeaders={"Origin":origin,"Content-Type":"application/x-www-form-urlencoded"};
  const anonymous=await browserResponse(request("/auth/link/github",formHeaders),identity,origin);
  assert.equal(anonymous?.status,401);
  assert.equal(calls.length,0,"No anonymous attempt may start a provider OAuth flow");

  identity.api.getSession=async()=>({user:{id:"owner"}});

  const get=await browserResponse(new Request(origin+"/auth/link/github"),identity,origin);
  assert.equal(get?.status,303);
  assert.equal(get?.headers.get("location"),"/account");

  const cross=await browserResponse(request("/auth/link/github",
    {...formHeaders,Origin:"https://attacker.invalid"}),identity,origin);
  assert.equal(cross?.status,403);

  const extra=await browserResponse(request("/auth/link/github",formHeaders,
    "callbackURL=https%3A%2F%2Fattacker.invalid"),identity,origin);
  assert.equal(extra?.status,400);

  const badContent=await browserResponse(request("/auth/link/github",
    {"Origin":origin,"Content-Type":"application/json"},"{}"),identity,origin);
  assert.equal(badContent?.status,415);
  assert.equal(calls.length,0,"Rejected requests must not invoke provider flows");
});

test("explicit provider linking forwards only signed-in session, uses allowlisted destination",async()=>{
  let payload:any,authCookie:string|null=null;
  const linked=mock() as BrowserIdentity & {api:any};
  linked.api={getSession:async()=>({user:{id:"owner"}})};
  linked.handler=async req=>{
    payload=await req.json();
    authCookie=req.headers.get("cookie");
    return new Response(JSON.stringify({
      url:"https://github.com/login/oauth/authorize",redirect:true
    }),{status:200,headers:{
      "content-type":"application/json",
      "set-cookie":"ba-state=opaque; Path=/; HttpOnly; SameSite=Lax"
    }});
  };
  const reply=await browserResponse(new Request(origin+"/auth/link/github",{
    method:"POST",headers:{
      "Origin":origin,"Cookie":"better-auth.session_token=opaque-session",
      "Content-Type":"application/x-www-form-urlencoded"
    },body:""
  }),linked,origin);
  assert.equal(reply?.status,303);
  assert.equal(reply?.headers.get("location"),"https://github.com/login/oauth/authorize");
  assert.match(reply?.headers.get("set-cookie")??"",/HttpOnly/);
  assert.equal(reply?.headers.get("cache-control"),"no-store");
  assert.equal(authCookie,"better-auth.session_token=opaque-session");
  assert.deepEqual(payload,{
    provider:"github",callbackURL:origin+"/account",disableRedirect:true
  });
  linked.handler=async()=>new Response(JSON.stringify({
    url:"https://attacker.invalid/redirect",redirect:true
  }),{status:200,headers:{"content-type":"application/json"}});
  const forged=await browserResponse(new Request(origin+"/auth/link/github",{
    method:"POST",headers:{Origin:origin,"Content-Type":"application/x-www-form-urlencoded"},
    body:""
  }),linked,origin);
  assert.equal(forged?.status,502);
});

test("unconfigured providers cannot be linked",async()=>{
  const onlyGithub=mock() as BrowserIdentity & {api:any;options:any};
  onlyGithub.options={socialProviders:{github:{}}};
  onlyGithub.api={getSession:async()=>({user:{id:"owner"}})};
  const forbidden=await browserResponse(new Request(origin+"/auth/link/google",{
    method:"POST",headers:{"Origin":origin,"Content-Type":"application/x-www-form-urlencoded"},body:""
  }),onlyGithub,origin);
  assert.equal(forbidden?.status,404);
});
