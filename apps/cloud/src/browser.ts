import { verifyOAuthQueryParams } from "@better-auth/oauth-provider";
import type { Identity } from "./identity.js";
import {renderSignIn,renderAccount,renderNotice} from "./browser-ui.js";

export type BrowserIdentity =
  Pick<Identity,"handler"> & Partial<Pick<Identity,"$context"|"api"|"options">>;
type SocialName="google"|"github";
function availableProviders(identity:BrowserIdentity):SocialName[]{
  const social=identity.options?.socialProviders;
  if(!social)return ["google","github"]; // test-only handler mocks
  return (["google","github"] as const).filter(name=>Boolean(social[name]));
}
const htmlHeaders = {
  "Content-Type":"text/html; charset=utf-8",
  "Cache-Control":"no-store",
  "X-Content-Type-Options":"nosniff",
  // HTML form navigations with no-referrer transmit Origin: null in Chrome;
  // same-origin preserves the verified Origin for first-party OAuth POSTs.
  "Referrer-Policy":"same-origin",
  "Content-Security-Policy":"default-src 'none'; base-uri 'none'; object-src 'none'; frame-ancestors 'none'; form-action 'self' https://github.com https://accounts.google.com; style-src 'self'"
};

function page(title:string,message:string,status=200):Response {
  return new Response(renderNotice(title,message),{status,headers:htmlHeaders});
}
async function checkedOAuthQuery(identity:BrowserIdentity,signed:string):Promise<boolean> {
  if (!identity.$context || signed.length>8192) return false;
  const {secret}=await identity.$context;
  return verifyOAuthQueryParams(signed,secret);
}
const trackingParams=new Set([
  "utm_source","utm_medium","utm_campaign","utm_term","utm_content"
]);
function trackingOnlySignInQuery(url:URL):boolean {
  if(!url.search || url.search.length>1024)return false;
  const keys=Array.from(url.searchParams.keys());
  return keys.length>0 && keys.length<=5 && keys.every(key=>trackingParams.has(key));
}
async function signInPage(url:URL,identity:BrowserIdentity):Promise<Response> {
  // Links from chat clients may append UTM metadata. Strip only an
  // exclusively-marketing query, never a mixed or signed OAuth request.
  if(trackingOnlySignInQuery(url)){
    return new Response(null,{
      status:303,
      headers:{"Location":"/sign-in","Cache-Control":"no-store"}
    });
  }
  const signed=url.search.slice(1);
  if(signed && !(await checkedOAuthQuery(identity,signed))) {
    return page("Invalid or expired authorization request","Restart the connection from your AI client.",400);
  }
  return new Response(renderSignIn(signed,availableProviders(identity)),{status:200,headers:htmlHeaders});
}

async function signedLoginForm(request:Request,identity:BrowserIdentity,publicOrigin:string):Promise<string|Response> {
  if(request.headers.get("origin")!==publicOrigin) return page("Forbidden","Start from the sign-in page.",403);
  if(request.headers.get("content-type")?.split(";")[0].trim()!=="application/x-www-form-urlencoded"){
    return page("Unsupported request","Invalid sign-in request.",415);
  }
  const raw=await request.text();
  if(raw.length>8192) return page("Invalid request","Request too large.",413);
  const fields=new URLSearchParams(raw);
  if(Array.from(fields.keys()).length!==1 || !fields.has("oauth_query")){
    return page("Invalid request","Unexpected login fields.",400);
  }
  const signed=fields.get("oauth_query")??"";
  if(signed && !(await checkedOAuthQuery(identity,signed))) {
    return page("Invalid authorization request","Restart the connection from your AI client.",400);
  }
  return signed;
}

async function approvedProviderRedirect(reply:Response,provider:"google"|"github"):Promise<Response> {
  if(!reply.ok) return page("Sign-in unavailable","Unable to start provider authentication.",502);
  const payload:unknown=await reply.json();
  if(!payload || typeof payload!=="object" || !("url" in payload) || typeof payload.url!=="string"){
    return page("Sign-in unavailable","Missing provider authorization URL.",502);
  }
  let next:URL;
  try {next=new URL(payload.url);}
  catch {return page("Sign-in unavailable","Invalid provider URL.",502);}
  const expected=provider==="google"?"accounts.google.com":"github.com";
  if(next.protocol!=="https:" || next.hostname!==expected) {
    return page("Sign-in unavailable","Unapproved provider destination.",502);
  }
  const headers=new Headers({"Location":next.href,"Cache-Control":"no-store","Referrer-Policy":"no-referrer"});
  for(const cookie of reply.headers.getSetCookie()) headers.append("Set-Cookie",cookie);
  return new Response(null,{status:303,headers});
}

async function startSocialLogin(request:Request,identity:BrowserIdentity,
  publicOrigin:string,provider:"google"|"github"):Promise<Response> {
  const signed=await signedLoginForm(request,identity,publicOrigin);
  if(signed instanceof Response) return signed;
  const authResponse=await identity.handler(new Request(publicOrigin+"/api/auth/sign-in/social",{
    method:"POST",
    headers:{
      "Content-Type":"application/json",
      "Origin":publicOrigin,
      ...(request.headers.get("cookie")?{"Cookie":request.headers.get("cookie")!}:{})
    },
    body:JSON.stringify({provider,callbackURL:publicOrigin+"/account",...(signed?{oauth_query:signed}:{})})
  }));
  return approvedProviderRedirect(authResponse,provider);
}

async function accountPage(request:Request,identity:BrowserIdentity):Promise<Response> {
  const session=await identity.api?.getSession({headers:request.headers});
  if(!session?.user) return new Response(null,{status:303,headers:{"Location":"/sign-in","Cache-Control":"no-store"}});
  return new Response(renderAccount(session.user.name??"User"),{status:200,headers:htmlHeaders});
}

export async function browserResponse(request:Request,identity:BrowserIdentity,publicOrigin:string):Promise<Response|null> {
  const url=new URL(request.url);
  if(url.pathname==="/sign-in" && request.method==="GET") return signInPage(url,identity);
  let provider: "google" | "github" | null = null;
  if (url.pathname === "/auth/start/google") provider = "google";
  else if (url.pathname === "/auth/start/github") provider = "github";
  // The OAuth start endpoint requires the CSRF-checked first-party POST.
  // A direct browser GET must never begin OAuth; guide the visitor to the form.
  if (provider && request.method === "GET") {
    return new Response(null,{status:303,headers:{"Location":"/sign-in","Cache-Control":"no-store"}});
  }
  if(provider && request.method==="POST") {
    if(!availableProviders(identity).includes(provider)){
      return page("Sign-in unavailable","This provider is not enabled.",404);
    }
    return startSocialLogin(request,identity,publicOrigin,provider);
  }
  if(url.pathname==="/account" && request.method==="GET") return accountPage(request,identity);
  return null;
}
