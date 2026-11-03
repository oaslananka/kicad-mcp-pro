import { randomBytes, timingSafeEqual } from "node:crypto";
import { makeSignature } from "better-auth/crypto";
import { renderConsentPage, type ConsentView } from "./consent-ui.js";
import { verifyOAuthQueryParams } from "@better-auth/oauth-provider";
import type { BrowserIdentity } from "./browser.js";

const TTL_MS = 300_000;
const HEADERS = {
  "Content-Type": "text/html; charset=utf-8",
  "Cache-Control": "no-store",
  // Native Chromium form POSTs send Origin: null under no-referrer;
  // same-origin keeps the strict Origin + CSRF checks enforceable.
  "Referrer-Policy": "same-origin",
  "X-Content-Type-Options": "nosniff",
  "Content-Security-Policy": "default-src 'none'; base-uri 'none'; object-src 'none'; frame-ancestors 'none'; form-action 'self'; style-src 'self'"
};
function callbackOrigin(signedQuery:string):string|null {
  const redirectUris=new URLSearchParams(signedQuery).getAll("redirect_uri");
  if(redirectUris.length!==1)return null;
  try{
    const url=new URL(redirectUris[0]);
    const loopback=url.protocol==="http:" && ["127.0.0.1","localhost"].includes(url.hostname);
    if((url.protocol!=="https:" && !loopback) || url.username || url.password || url.hash)return null;
    return url.origin;
  }catch{return null;}
}
function renderConsentResponse(view:ConsentView, status=200, cookie?:string):Response {
  const headers=new Headers(HEADERS);
  if(view.kind==="approve"){
    // Only signed, registered OAuth requests reach this page. A native form
    // POST may follow Better Auth's validated callback redirect; CSP must
    // permit that single verified client origin, never arbitrary providers.
    const callback=callbackOrigin(view.query);
    if(callback)headers.set("Content-Security-Policy",
      HEADERS["Content-Security-Policy"].replace("form-action 'self';",
        `form-action 'self' ${callback};`));
  }
  if(cookie) headers.append("Set-Cookie",cookie);
  return new Response(renderConsentPage(view),{status,headers});
}
function error(status=400):Response {
  return renderConsentResponse({kind:"notice",message:"Authorization request could not be verified. Restart the connection in your AI client."},status);
}
function queryValid(query:string):boolean {
  const params=new URLSearchParams(query);
  const clientIds=params.getAll("client_id");
  const scopes=params.getAll("scope");
  return query.length <= 8192 && clientIds.length === 1 &&
    !!clientIds[0] && clientIds[0].length<=1024 &&
    scopes.length === 1 && !!scopes[0] && scopes[0].length<=2048;
}
async function verifyQuery(identity:BrowserIdentity, query:string):Promise<boolean> {
  if(!queryValid(query) || !identity.$context) return false;
  const {secret}=await identity.$context;
  return verifyOAuthQueryParams(query,secret);
}
function sessionFor(identity:BrowserIdentity, request:Request) {
  return identity.api?.getSession({headers:request.headers});
}
async function approvedClient(identity:BrowserIdentity,request:Request,origin:string,clientId:string):Promise<string|null> {
  const response=await identity.handler(new Request(origin+"/api/auth/oauth2/public-client?client_id="+encodeURIComponent(clientId),{
    method:"GET",headers:{"Cookie":request.headers.get("cookie")??""}
  }));
  if(!response.ok) return null;
  const client:unknown=await response.json();
  if(!client || typeof client!=="object" || !("client_id" in client) || client.client_id!==clientId) return null;
  if("client_name" in client && typeof client.client_name==="string" && client.client_name.length>0) return client.client_name;
  return clientId;
}
function accessAllowed(query:string, managementClientId:string):boolean {
  const params=new URLSearchParams(query);
  const scopes=new Set((params.get("scope")??"").split(/\s+/).filter(Boolean));
  return !scopes.has("projects:manage") || (!!managementClientId && params.get("client_id")===managementClientId);
}
async function consentSignature(secret:string,userId:string,query:string,nonce:string,time:number):Promise<string> {
  const message=JSON.stringify(["consent-v1",userId,query,nonce,time]);
  const signature=await makeSignature(message,secret);
  return Buffer.from(signature,"base64").toString("base64url");
}
function cookieName(origin:string):string {
  return origin.startsWith("https://") ? "__Host-kicad-consent" : "kicad-consent";
}
function consentCookie(request:Request,origin:string):string|null {
  const name=cookieName(origin);
  const cookie=request.headers.get("cookie")??"";
  const match=cookie.split(";").map(c=>c.trim()).find(c=>c.startsWith(name+"="));
  return match ? match.slice(name.length+1) : null;
}
function csrfCookie(value:string,origin:string,maxAge:number):string {
  return cookieName(origin)+"="+value+"; Path=/; HttpOnly; SameSite=Strict; Max-Age="+maxAge+
    (origin.startsWith("https://")?"; Secure":"");
}
async function csrfValid(cookie:string|null,form:string,secret:string,userId:string,query:string):Promise<boolean> {
  if(!cookie || !form || cookie!==form || form.length>250) return false;
  const parts=form.split(".");
  if(parts.length!==3 || !/^\d{13}$/.test(parts[0]) || !/^[a-zA-Z0-9_-]{22}$/.test(parts[1]) ||
    !/^[a-zA-Z0-9_-]{43}$/.test(parts[2])) return false;
  const time=Number(parts[0]);
  if(time>Date.now()+5000 || Date.now()-time>TTL_MS) return false;
  const expected=await consentSignature(secret,userId,query,parts[1],time);
  const a=Buffer.from(expected);
  const b=Buffer.from(parts[2]);
  return a.length===b.length && timingSafeEqual(a,b);
}
function redirectResponse(response:Response,origin:string):Promise<Response> {
  return (async()=>{
    if(!response.ok) return error(502);
    const raw:unknown=await response.json();
    if(!raw || typeof raw!=="object" || !("url" in raw) || typeof raw.url!=="string") return error(502);
    let url:URL;
    try{url=new URL(raw.url);}catch{return error(502);}
    const local=url.protocol==="http:" && ["127.0.0.1","localhost"].includes(url.hostname);
    if(url.protocol!=="https:" && !local) return error(502);
    const headers=new Headers({"Location":url.href,"Cache-Control":"no-store","Referrer-Policy":"no-referrer"});
    for(const cookie of response.headers.getSetCookie()) headers.append("Set-Cookie",cookie);
    headers.append("Set-Cookie",csrfCookie("",origin,0));
    return new Response(null,{status:303,headers});
  })();
}
async function consentGet(request:Request,identity:BrowserIdentity,origin:string,managementClientId:string):Promise<Response> {
  const query=new URL(request.url).search.slice(1);
  if(!(await verifyQuery(identity,query)) || !accessAllowed(query,managementClientId)) return error(403);
  const session=await sessionFor(identity,request);
  if(!session?.user?.id) return new Response(null,{status:303,headers:{"Location":"/sign-in?"+query,"Cache-Control":"no-store"}});
  const params=new URLSearchParams(query);
  const clientId=params.get("client_id");
  if (!clientId || !identity.$context) return error(403);
  const name=await approvedClient(identity,request,origin,clientId);
  if(!name) return error(403);
  const {secret}=await identity.$context;
  const now=Date.now();
  const nonce=randomBytes(16).toString("base64url");
  const token=[now,nonce,await consentSignature(secret,session.user.id,query,nonce,now)].join(".");
  const scopes=(params.get("scope")??"").split(/\s+/).filter(Boolean);
  const claims=params.get("claims");
  return renderConsentResponse({
    kind:"approve",clientName:name,scopes,claims:claims??undefined,query,csrf:token
  },200,csrfCookie(token,origin,300));
}
async function consentPost(request:Request,identity:BrowserIdentity,origin:string,managementClientId:string):Promise<Response> {
  if(request.headers.get("origin")!==origin) return error(403);
  if(request.headers.get("content-type")?.split(";")[0].trim()!=="application/x-www-form-urlencoded") return error(415);
  const raw=await request.text();
  if(raw.length>12_000) return error(413);
  const fields=new URLSearchParams(raw);
  if(Array.from(fields.keys()).length!==3 || ["oauth_query","csrf","decision"].some(key=>fields.getAll(key).length!==1)) return error();
  const query=fields.get("oauth_query")??"";
  const decision=fields.get("decision");
  if(!["approve","deny"].includes(decision??"")) return error();
  if(!(await verifyQuery(identity,query)) || !accessAllowed(query,managementClientId)) return error(403);
  const session=await sessionFor(identity,request);
  if(!session?.user?.id) return error(401);
  const clientId=new URLSearchParams(query).get("client_id");
  if(!clientId || !identity.$context) return error(403);
  if(!(await approvedClient(identity,request,origin,clientId))) return error(403);
  const {secret}=await identity.$context;
  if(!(await csrfValid(consentCookie(request,origin),fields.get("csrf")??"",secret,session.user.id,query))) return error(403);
  const reply=await identity.handler(new Request(origin+"/api/auth/oauth2/consent",{
    method:"POST",
    headers:{"Content-Type":"application/json","Origin":origin,"Cookie":request.headers.get("cookie")??""},
    body:JSON.stringify({accept:decision==="approve",oauth_query:query})
  }));
  return redirectResponse(reply,origin);
}
export async function consentResponse(request:Request,identity:BrowserIdentity,origin:string,managementClientId=""):Promise<Response|null> {
  const url=new URL(request.url);
  if(url.pathname!=="/consent") return null;
  if(request.method==="GET") return consentGet(request,identity,origin,managementClientId);
  if(request.method==="POST") return consentPost(request,identity,origin,managementClientId);
  return error(405);
}
