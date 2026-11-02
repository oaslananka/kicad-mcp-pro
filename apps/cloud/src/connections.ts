import {randomBytes, timingSafeEqual} from "node:crypto";
import {makeSignature} from "better-auth/crypto";
import type {BrowserIdentity} from "./browser.js";
import type {GrantManagement} from "./grants.js";
import {renderConnectionsPage, type DisplayConnection} from "./connections-ui.js";

const FIVE_MINUTES=300_000;
function cookieName(origin:string):string {
  return origin.startsWith("https://") ? "__Host-kicad-connections" : "kicad-connections";
}
function cookie(value:string,origin:string,age:number):string {
  return cookieName(origin)+"="+value+"; Path=/; HttpOnly; SameSite=Strict; Max-Age="+age+
    (origin.startsWith("https://")?"; Secure":"");
}
function readCookie(request:Request,origin:string):string|null {
  const name=cookieName(origin);
  return (request.headers.get("cookie")??"").split(";").map(v=>v.trim())
    .find(v=>v.startsWith(name+"="))?.slice(name.length+1)??null;
}
function page(connections:DisplayConnection[],status=200,extraCookie?:string,
  notice?:string,publicOrigin?:string):Response {
  const response = new Response(renderConnectionsPage(connections,notice,publicOrigin),{status});
  response.headers.set("Content-Type","text/html; charset=utf-8");
  response.headers.set("Cache-Control","no-store");
  // Same-origin form POSTs must retain the real Origin; no-referrer sends Origin: null.
  // Keep referrers hidden from other sites without weakening CSRF/Origin checks.
  response.headers.set("Referrer-Policy","same-origin");
  response.headers.set("X-Content-Type-Options","nosniff");
  response.headers.set("Content-Security-Policy",
    "default-src 'none'; base-uri 'none'; object-src 'none'; frame-ancestors 'none'; form-action 'self'; style-src 'self'");
  if(extraCookie) response.headers.append("Set-Cookie",extraCookie);
  return response;
}
function failure(code:number):Response {
  return page([],code,undefined,"Access could not be changed. Please reload your connections.");
}
async function sign(secret:string,user:string,session:string,id:string,client:string,timestamp:string,nonce:string):Promise<string> {
  const raw=JSON.stringify(["revoke-v1",user,session,id,client,timestamp,nonce]);
  const result=await makeSignature(raw,secret);
  return Buffer.from(result,"base64").toString("base64url");
}
async function token(secret:string,user:string,session:string,id:string,client:string,stamp:string,nonce:string):Promise<string> {
  return stamp+"."+nonce+"."+(await sign(secret,user,session,id,client,stamp,nonce));
}
type RevokeProof = {secret:string;user:string;session:string;id:string;client:string;submitted:string};
async function validToken(request:Request,origin:string,proof:RevokeProof):Promise<boolean> {
  const {secret,user,session,id,client,submitted}=proof;
  const state=readCookie(request,origin);
  if(!state || submitted.length>250) return false;
  const [stamp,nonce,sig,...extra]=submitted.split(".");
  if(extra.length || !/^\d{13}$/.test(stamp) || !/^[a-zA-Z0-9_-]{22}$/.test(nonce) ||
    !/^[a-zA-Z0-9_-]{43}$/.test(sig)) return false;
  if(state!==stamp+"."+nonce) return false;
  const time=Number(stamp);
  if(time>Date.now()+5000 || Date.now()-time>FIVE_MINUTES) return false;
  const expected=Buffer.from(await sign(secret,user,session,id,client,stamp,nonce));
  const received=Buffer.from(sig);
  return expected.length===received.length && timingSafeEqual(expected,received);
}
function sessionUser(session:Awaited<ReturnType<NonNullable<BrowserIdentity["api"]>["getSession"]>>) {
  if (!session?.user?.id || !session.session?.id) return null;
  return {user:session.user.id,session:session.session.id};
}
async function list(request:Request,identity:BrowserIdentity,origin:string):Promise<Response> {
  if(!identity.api || !identity.$context) return failure(503);
  const session=await identity.api.getSession({headers:request.headers});
  const owner=sessionUser(session);
  if(!owner) return new Response(null,{status:303,headers:{"Location":"/sign-in","Cache-Control":"no-store"}});
  const consents=await identity.api.getOAuthConsents({headers:request.headers});
  if(!Array.isArray(consents)) return failure(502);
  const eligible=consents.filter(c=>c.userId===owner.user && typeof c.id==="string" && typeof c.clientId==="string").slice(0,100);
  const {secret}=await identity.$context;
  const stamp=String(Date.now());
  const nonce=randomBytes(16).toString("base64url");
  const rows:DisplayConnection[]=await Promise.all(eligible.map(async consent=>{
    // Internal registered client id is the stable displayed fallback.
    const clientId=consent.clientId;
    const clientResponse=await identity.handler(new Request(origin+"/api/auth/oauth2/public-client?client_id="+encodeURIComponent(clientId),{
      headers:{"Cookie":request.headers.get("cookie")??""}
    }));
    const meta:unknown=clientResponse.ok ? await clientResponse.json() : null;
    const name=meta && typeof meta==="object" && "client_id" in meta && meta.client_id===clientId &&
      "client_name" in meta && typeof meta.client_name==="string" && meta.client_name ? meta.client_name : clientId;
    return {id:consent.id,clientId,name,scopes:consent.scopes,
      csrf:await token(secret,owner.user,owner.session,consent.id,clientId,stamp,nonce)};
  }));
  const notice=new URL(request.url).searchParams.has("removed") ? "Connection access was removed. Project grants were disabled." : undefined;
  return page(rows,200,cookie(stamp+"."+nonce,origin,300),notice,origin);
}
async function revoke(request:Request,identity:BrowserIdentity,origin:string,grants:Pick<GrantManagement,"revokeClient">):Promise<Response> {
  if(!identity.api || !identity.$context) return failure(503);
  if(request.headers.get("origin")!==origin) return failure(403);
  if(request.headers.get("content-type")?.split(";")[0].trim()!=="application/x-www-form-urlencoded") return failure(415);
  const raw=await request.text();
  if(raw.length>8192) return failure(413);
  const data=new URLSearchParams(raw);
  const keys=["id","client_id","csrf"];
  if(Array.from(data.keys()).length!==3 || keys.some(k=>data.getAll(k).length!==1)) return failure(400);
  const id=data.get("id")??"", clientId=data.get("client_id")??"", csrf=data.get("csrf")??"";
  if(!id || id.length>256 || !clientId || clientId.length>1024) return failure(400);
  const session=await identity.api.getSession({headers:request.headers});
  const owner=sessionUser(session);
  if(!owner) return failure(401);
  const {secret}=await identity.$context;
  if(!(await validToken(request,origin,{secret,user:owner.user,session:owner.session,id,client:clientId,submitted:csrf}))) return failure(403);
  let consent;
  try {
    consent=await identity.api.getOAuthConsent({query:{id},headers:request.headers});
  }catch{return failure(404);}
  if(!consent || consent.userId!==owner.user || consent.clientId!==clientId) return failure(404);
  // Fail closed: first disable every grant, so outstanding stateless JWTs
  // cannot read projects even if OAuth deletion subsequently fails.
  try {await grants.revokeClient(owner.user,clientId);}
  catch {return failure(503);}
  try {
    await identity.api.deleteOAuthConsent({body:{id},headers:request.headers});
  }catch {
    // Grants remain disabled, but never claim complete OAuth revocation.
    return failure(502);
  }
  return new Response(null,{status:303,headers:{
    "Location":"/connections?removed=1","Cache-Control":"no-store",
    "Set-Cookie":cookie("",origin,0)
  }});
}
export async function connectionsResponse(request:Request,identity:BrowserIdentity,origin:string,grants?:Pick<GrantManagement,"revokeClient">):Promise<Response|null> {
  const path=new URL(request.url).pathname;
  if(path==="/connections" && request.method==="GET") return list(request,identity,origin);
  if(path==="/connections/revoke" && request.method==="POST") {
    return grants ? revoke(request,identity,origin,grants) : failure(503);
  }
  return null;
}
