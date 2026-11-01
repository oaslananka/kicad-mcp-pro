import {randomUUID,timingSafeEqual} from "node:crypto";
import type {IncomingMessage,ServerResponse} from "node:http";
import type {RegistrationResponseJSON} from "@simplewebauthn/server";
import {PgOwnerReadPasskeyRegistration}
  from "./owner-read-passkey-registration.js";

/**
 * Standalone handler for a separately deployed owner authority, NOT mounted
 * by Cloud's production router. Authenticated owner + CSRF token MUST be
 * supplied by the independent owner-session verifier, never request headers,
 * OAuth client metadata, query parameters or body-submitted owner IDs.
 */
export type OwnerRegistrationSession=Readonly<{ownerSub:string;csrf:string}>;
export type RegistrationSessionVerifier=
  (request:IncomingMessage)=>Promise<OwnerRegistrationSession|null>;
export function createOwnerRegistrationHandler(
  registrar:PgOwnerReadPasskeyRegistration,
  authorityOrigin:string,authenticate:RegistrationSessionVerifier
){
  const origin=new URL(authorityOrigin);
  if(origin.protocol!=="https:"||origin.origin!==authorityOrigin)
    throw Error("Registration authority must use exact HTTPS origin");
  return async function handle(request:IncomingMessage,
    response:ServerResponse):Promise<void>{
    const send=(status:number,data:unknown)=>{
      if(response.headersSent)return;
      response.writeHead(status,{
        "Content-Type":"application/json; charset=utf-8",
        "Cache-Control":"no-store","X-Content-Type-Options":"nosniff",
        "Referrer-Policy":"no-referrer","Vary":"Origin"
      });
      response.end(JSON.stringify(data));
    };
    const begin=request.url==="/owner-passkey/register/begin";
    const complete=request.url==="/owner-passkey/register/complete";
    if(!begin&&!complete){send(404,{error:"not_found"});return;}
    if(request.method!=="POST"||
       request.headers.origin!==authorityOrigin||
       request.headers["content-type"]!=="application/json"||
       (request.headers["sec-fetch-site"]&&
        request.headers["sec-fetch-site"]!=="same-origin")){
      send(403,{error:"denied"});return;
    }
    try{
      const session=await authenticate(request);
      if(!session?.ownerSub||!session.csrf){
        send(403,{error:"denied"});return;
      }
      let total=0;
      const chunks:Buffer[]=[];
      for await(const chunk of request){
        const bytes=Buffer.from(chunk as Uint8Array);
        total+=bytes.length;
        if(total>16_384){send(413,{error:"too_large"});return;}
        chunks.push(bytes);
      }
      const parsed=JSON.parse(Buffer.concat(chunks).toString("utf8")) as {
        csrf?:unknown;requestId?:unknown;response?:RegistrationResponseJSON
      };
      const proof=typeof parsed?.csrf==="string"?
        Buffer.from(parsed.csrf):Buffer.alloc(0);
      const secret=Buffer.from(session.csrf);
      if(proof.length===0||proof.length!==secret.length||
        !timingSafeEqual(proof,secret)){send(403,{error:"denied"});return;}
      if(begin){
        // Never trust caller-supplied registration identity or request UUID.
        const requestId=randomUUID();
        const options=await registrar.begin(session.ownerSub,requestId);
        if(!options){send(403,{error:"denied"});return;}
        send(200,{requestId,options});
      }else{
        if(typeof parsed.requestId!=="string"||
          !parsed.response||typeof parsed.response!=="object"){
          send(400,{error:"invalid_request"});return;
        }
        const verdict=await registrar.complete(session.ownerSub,
          parsed.requestId,parsed.response);
        if(verdict!=="registered_inactive"){
          send(403,{error:"denied"});return;
        }
        send(201,{state:"registered_inactive"});
      }
    }catch{
      send(403,{error:"denied"});
    }
  };
}
