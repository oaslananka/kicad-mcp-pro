import {randomBytes,timingSafeEqual} from "node:crypto";
import {makeSignature} from "better-auth/crypto";
import type {BrowserIdentity} from "./browser.js";
import type {PairingReviewPort} from "./pairing-review.js";
import {renderPairingReviewPage} from "./pairing-review-ui.js";

const UUID=/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
function cookieName(origin:string){
  return origin.startsWith("https://")?"__Host-kicad-pairing-review":"kicad-pairing-review";
}
function stateCookie(value:string,origin:string,maxAge:number){
  return cookieName(origin)+"="+value+"; Path=/; HttpOnly; SameSite=Strict; Max-Age="+maxAge+
    (origin.startsWith("https://")?"; Secure":"");
}
function getCookie(req:Request,origin:string){
  const name=cookieName(origin);
  return (req.headers.get("cookie")??"").split(";").map(x=>x.trim())
    .find(x=>x.startsWith(name+"="))?.slice(name.length+1)??null;
}
function page(status:number,csrf="",notice?:string,cookie?:string):Response{
  const res=new Response(renderPairingReviewPage(csrf,notice),{status,headers:{
    "Content-Type":"text/html; charset=utf-8","Cache-Control":"no-store",
    "Referrer-Policy":"same-origin","X-Content-Type-Options":"nosniff",
    "Content-Security-Policy":"default-src 'none'; base-uri 'none'; object-src 'none'; frame-ancestors 'none'; form-action 'self'; style-src 'self'; script-src 'self'"
  }});
  if(cookie)res.headers.append("Set-Cookie",cookie);
  return res;
}
function denied(status:number){
  return page(status,"","Pairing request denied. Reload the approval page to try again.");
}
function user(session:Awaited<ReturnType<NonNullable<BrowserIdentity["api"]>["getSession"]>>){
  if(!session?.user?.id||!session.session?.id)return null;
  return {id:session.user.id,session:session.session.id};
}
async function signature(secret:string,owner:string,session:string,stamp:string,nonce:string){
  return Buffer.from(await makeSignature(JSON.stringify([
    "pairing-review-csrf-v1",owner,session,stamp,nonce
  ]),secret),"base64").toString("base64url");
}
async function verifyCsrf(req:Request,origin:string,secret:string,
  owner:{id:string;session:string},proof:string):Promise<boolean>{
  if(typeof proof!=="string"||proof.length>250)return false;
  const [stamp,nonce,sig,...rest]=proof.split(".");
  if(rest.length||!/^\d{13}$/.test(stamp)||!/^[A-Za-z0-9_-]{22}$/.test(nonce)||
     !/^[A-Za-z0-9_-]{43}$/.test(sig))return false;
  if(getCookie(req,origin)!==stamp+"."+nonce)return false;
  const now=Date.now(),created=Number(stamp);
  if(created>now+5000||now-created>300_000)return false;
  const expected=Buffer.from(await signature(secret,owner.id,owner.session,stamp,nonce));
  const actual=Buffer.from(sig);
  return expected.length===actual.length&&timingSafeEqual(expected,actual);
}

/**
 * Browser-only pre-enrollment approval; not a pairing issuance endpoint.
 * Device enrollment still requires its independent one-use private-key proof.
 */
export async function pairingBrowserResponse(
  req:Request,identity:BrowserIdentity,origin:string,
  pairings?:PairingReviewPort
):Promise<Response|null>{
  const path=new URL(req.url).pathname;
  if(path!=="/devices/pairing"&&path!=="/devices/pairing/review")return null;
  if(!pairings||!identity.api||!identity.$context)return denied(503);
  if(path==="/devices/pairing"&&req.method==="GET"){
    const actor=user(await identity.api.getSession({headers:req.headers}));
    if(!actor)return new Response(null,{status:303,headers:{
      Location:"/sign-in","Cache-Control":"no-store"
    }});
    const {secret}=await identity.$context;
    const stamp=String(Date.now()),nonce=randomBytes(16).toString("base64url");
    const proof=stamp+"."+nonce+"."+
      await signature(secret,actor.id,actor.session,stamp,nonce);
    // A query string must never be treated as proof that pairing succeeded.
    return page(200,proof,undefined,stateCookie(stamp+"."+nonce,origin,300));
  }
  if(path!=="/devices/pairing/review"||req.method!=="POST")return denied(405);
  if(req.headers.get("origin")!==origin)return denied(403);
  if(req.headers.get("content-type")?.split(";")[0].trim()!=="application/x-www-form-urlencoded")
    return denied(415);
  const raw=await req.text();
  if(raw.length>2048)return denied(413);
  const fields=new URLSearchParams(raw);
  const names=["challenge_id","user_code","decision","csrf"];
  if([...fields.keys()].length!==names.length||
    names.some(name=>fields.getAll(name).length!==1))return denied(400);
  const id=fields.get("challenge_id")??"",code=fields.get("user_code")??"";
  const decision=fields.get("decision");
  if(!UUID.test(id)||code.length>20||code.length<12||
    (decision!=="approve"&&decision!=="deny"))return denied(400);
  const actor=user(await identity.api.getSession({headers:req.headers}));
  if(!actor)return denied(401);
  const {secret}=await identity.$context;
  if(!await verifyCsrf(req,origin,secret,actor,fields.get("csrf")??""))return denied(403);
  let verdict:Awaited<ReturnType<PairingReviewPort["review"]>>;
  try{verdict=await pairings.review(id,actor.id,code,decision);}
  catch{return denied(503);}
  if(verdict==="throttled")return denied(429);
  if(verdict!=="approved"&&verdict!=="denied")return denied(400);
  return new Response(null,{status:303,headers:{
    Location:"/devices/pairing","Cache-Control":"no-store",
    "Set-Cookie":stateCookie("",origin,0)
  }});
}
