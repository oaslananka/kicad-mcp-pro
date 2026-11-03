import {timingSafeEqual} from "node:crypto";
import type {IncomingMessage,ServerResponse} from "node:http";
import type {AuthenticationResponseJSON,PublicKeyCredentialRequestOptionsJSON}
  from "@simplewebauthn/server";
import type {RegistrationSessionVerifier} from "./owner-read-registration-http.js";
import type {OwnerReadApprovalIntent,PgOwnerReadWebAuthnIssuer}
  from "./owner-read-webauthn-issuer.js";
import {renderOwnerReadReview,ownerReadReviewHeaders}
  from "./owner-read-approval-ui.js";

const UUID=/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
type Issuer=Pick<PgOwnerReadWebAuthnIssuer,"begin"|"approve">;
type Pending={
  intent:OwnerReadApprovalIntent;credentialId:string;
  options?:PublicKeyCredentialRequestOptionsJSON;
  deadline:number;started:boolean;
};
/**
 * Standalone, inert owner-issuer review handler. Only an already-trusted
 * server component may inject an exact intent using addTrustedIntent().
 * There is NO HTTP route that creates, changes, or imports approval scope.
 *
 * The separate issuer SQL role alone can INSERT owner approval receipts.
 * Registration, passkey activation and Cloud connector reads stay elsewhere.
 */
export function createOwnerReadReviewHandler(
  issuer:Issuer,authorityOrigin:string,
  authenticate:RegistrationSessionVerifier,
  reviewScript:Buffer
){
  const authority=new URL(authorityOrigin);
  if(authority.protocol!=="https:"||authority.origin!==authorityOrigin||
     authority.pathname!=="/"||authority.search||authority.hash||
     !reviewScript.length||reviewScript.length>24_000)
    throw Error("Separate owner review requires exact HTTPS authority");
  const pending=new Map<string,Pending>();
  const deny=(res:ServerResponse,status=403)=>{
    if(res.headersSent)return;
    res.writeHead(status,{"Content-Type":"application/json; charset=utf-8",
      "Cache-Control":"no-store","X-Content-Type-Options":"nosniff",
      "Referrer-Policy":"no-referrer"});
    res.end(JSON.stringify({error:"denied"}));
  };
  const clean=()=>{
    const now=Date.now();
    for(const [id,entry] of pending){
      if(entry.deadline<=now)pending.delete(id);
    }
  };
  const addTrustedIntent=(intent:OwnerReadApprovalIntent,credentialId:string)=>{
    clean();
    if(pending.size>=64||!intent||!UUID.test(intent.requestId)||
       !UUID.test(intent.deviceId)||!UUID.test(intent.projectId)||
       typeof intent.ownerSub!=="string"||!intent.ownerSub||intent.ownerSub.length>256||
       typeof intent.clientId!=="string"||!intent.clientId||intent.clientId.length>1024||
       !/^[A-Za-z0-9_-]{24,1024}$/.test(credentialId)||
       !Number.isSafeInteger(intent.expiresAtUnixMs)||
       intent.expiresAtUnixMs-Date.now()<5_000||
       intent.expiresAtUnixMs-Date.now()>30_000||
       pending.has(intent.requestId))return false;
    try{
      const origin=new URL(intent.origin);
      if(origin.protocol!=="https:"||origin.origin!==intent.origin||
         origin.pathname!=="/"||origin.search||origin.hash||
         origin.username||origin.password)return false;
    }catch{return false;}
    pending.set(intent.requestId,{
      intent:Object.freeze({...intent}),credentialId,
      deadline:intent.expiresAtUnixMs,started:false
    });
    return true;
  };
  const handle=async(req:IncomingMessage,res:ServerResponse)=>{
    const raw=req.url??"";
    if(req.headers.host!==authority.host||raw.length>512||
       !raw.startsWith("/")||raw.startsWith("//")||
       req.headers.authorization!==undefined||
       req.headers["x-forwarded-host"]!==undefined||
       req.headers["x-forwarded-proto"]!==undefined){
      deny(res);return;
    }
    if(raw==="/owner-read/review.js"&&req.method==="GET"){
      res.writeHead(200,{"Content-Type":"text/javascript; charset=utf-8",
        "Cache-Control":"no-store","X-Content-Type-Options":"nosniff",
        "Referrer-Policy":"no-referrer"});
      res.end(reviewScript);return;
    }
    let url:URL;
    try{url=new URL(authorityOrigin+raw);}
    catch{deny(res);return;}
    const view=url.pathname==="/owner-read/review"&&req.method==="GET";
    const approve=raw==="/owner-read/approval"&&req.method==="POST";
    if(!view&&!approve){deny(res,404);return;}
    if(approve&&(req.headers.origin!==authorityOrigin||
       req.headers["content-type"]!=="application/json"||
       (req.headers["sec-fetch-site"]&&
        req.headers["sec-fetch-site"]!=="same-origin"))){
      deny(res);return;
    }
    try{
      const session=await authenticate(req);
      if(!session?.ownerSub||!session.csrf){deny(res);return;}
      clean();
      if(view){
        if(url.searchParams.size!==1||!url.searchParams.has("requestId")){
          deny(res,404);return;
        }
        const id=url.searchParams.get("requestId")??"";
        if(!UUID.test(id)){deny(res,404);return;}
        const item=pending.get(id);
        if(!item||item.intent.ownerSub!==session.ownerSub){
          deny(res,404);return;
        }
        if(!item.options&&!item.started){
          item.started=true;
          const generated=await issuer.begin(item.intent,item.credentialId);
          if(!generated){pending.delete(id);deny(res);return;}
          item.options=generated;
        }
        if(!item.options){deny(res);return;}
        const html=renderOwnerReadReview({
          intent:item.intent,options:item.options
        },session.ownerSub,authorityOrigin,session.csrf);
        res.writeHead(200,ownerReadReviewHeaders);
        res.end(html);
        return;
      }
      let size=0;
      const chunks:Buffer[]=[];
      for await(const chunk of req){
        const bytes=Buffer.from(chunk as Uint8Array);
        size+=bytes.length;
        if(size>24_000){deny(res,413);return;}
        chunks.push(bytes);
      }
      const payload=JSON.parse(Buffer.concat(chunks).toString("utf8")) as {
        requestId?:unknown;challenge?:unknown;csrf?:unknown;
        assertion?:AuthenticationResponseJSON;
      };
      if(!payload||typeof payload!=="object"||
         Object.keys(payload).length!==4||
         !["requestId","challenge","csrf","assertion"].every(
           name=>Object.hasOwn(payload,name))||
         typeof payload.requestId!=="string"||
         typeof payload.challenge!=="string"||
         typeof payload.csrf!=="string"||
         typeof payload.assertion!=="object"||!payload.assertion||
         !UUID.test(payload.requestId)){deny(res);return;}
      const expected=Buffer.from(session.csrf);
      const supplied=Buffer.from(payload.csrf);
      if(expected.length!==supplied.length||
         !timingSafeEqual(expected,supplied)){deny(res);return;}
      const item=pending.get(payload.requestId);
      if(!item||item.intent.ownerSub!==session.ownerSub||
         !item.options){deny(res);return;}
      const expectedChallenge=Buffer.from(item.options.challenge);
      const suppliedChallenge=Buffer.from(payload.challenge);
      // Denied or malformed submissions do not leave a reusable challenge.
      pending.delete(payload.requestId);
      if(expectedChallenge.length!==suppliedChallenge.length||
         !timingSafeEqual(expectedChallenge,suppliedChallenge)){
        deny(res);return;
      }
      const approved=await issuer.approve(
        payload.requestId,payload.challenge,payload.assertion);
      if(!approved){deny(res);return;}
      res.writeHead(204,{"Cache-Control":"no-store",
        "Referrer-Policy":"no-referrer","X-Content-Type-Options":"nosniff"});
      res.end();
    }catch{deny(res);}
  };
  return {addTrustedIntent,handle};
}
