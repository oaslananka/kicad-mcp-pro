import {createServer as createHttpsServer,type ServerOptions} from "node:https";
import type {IncomingMessage,ServerResponse} from "node:http";
import type {Identity} from "./identity.js";
import {browserResponse} from "./browser.js";
import type {RegistrationSessionVerifier} from "./owner-read-registration-http.js";
import {createOwnerRegistrationHandler} from "./owner-read-registration-http.js";
import type {PgOwnerReadPasskeyRegistration} from "./owner-read-passkey-registration.js";
import {createOwnerPasskeyEnrollmentPageHandler} from "./owner-read-enrollment-ui.js";

/**
 * Standalone HTTPS acceptance host for real first-party Better Auth login and
 * INACTIVE passkey registration. Never mount this on the Cloud MCP app.
 * No passkey activation, approval issuance, WSS or KiCad read routes exist.
 *
 * TLS must be terminated in this process, not spoofed by forwarding headers.
 * Deployment and secrets remain independently provisioned and off by default.
 */
export function createOwnerAcceptanceServer(options:{
  authorityOrigin:string;
  identity:Pick<Identity,"handler"|"api"|"options">;
  sessionVerifier:RegistrationSessionVerifier;
  registration:PgOwnerReadPasskeyRegistration;
  tls:Pick<ServerOptions,"key"|"cert">;
  clientScript:Buffer;
  /** Optional independent review role; NEVER supplied by owner:acceptance CLI.
   * The caller must first verify a dedicated issuer SQL role and Cloud
   * signature public key. Without both callbacks all routes stay absent.
   */
  approval?:Readonly<{
    receiveSignedIntent:(req:IncomingMessage,res:ServerResponse)=>Promise<void>;
    review:(req:IncomingMessage,res:ServerResponse)=>Promise<void>;
  }>;
}){
  const authority=new URL(options.authorityOrigin);
  if(authority.protocol!=="https:"||
     authority.origin!==options.authorityOrigin||
     authority.pathname!=="/"||authority.search||authority.hash||
     options.identity.options.baseURL!==options.authorityOrigin||
     !options.tls.key||!options.tls.cert||
     options.clientScript.length<100||options.clientScript.length>24_000)
    throw Error("Owner acceptance requires an independent exact HTTPS authority");

  const page=createOwnerPasskeyEnrollmentPageHandler(
    options.authorityOrigin,options.sessionVerifier);
  const register=createOwnerRegistrationHandler(
    options.registration,options.authorityOrigin,options.sessionVerifier);
  const send=(response:ServerResponse,status:number,data:object)=>{
    response.writeHead(status,{
      "Content-Type":"application/json; charset=utf-8",
      "Cache-Control":"no-store","X-Content-Type-Options":"nosniff"
    });
    response.end(JSON.stringify(data));
  };
  const emit=async(response:ServerResponse,reply:Response)=>{
    const headers:Object=Object.fromEntries(reply.headers);
    const clean:Record<string,string|string[]>={};
    for(const [name,value] of Object.entries(headers)){
      if(!["set-cookie","content-length","transfer-encoding",
        "connection","keep-alive"].includes(name.toLowerCase()))
        clean[name]=value as string;
    }
    clean["Cache-Control"]="no-store";
    clean["X-Content-Type-Options"]="nosniff";
    const cookies=reply.headers.getSetCookie();
    if(cookies.length)clean["Set-Cookie"]=cookies;
    response.writeHead(reply.status,clean);
    response.end(Buffer.from(await reply.arrayBuffer()));
  };
  const route=async(req:IncomingMessage,res:ServerResponse)=>{
    const url=req.url??"";
    if(url.length>4096||!url.startsWith("/")||url.startsWith("//")||
       req.headers.host!==authority.host||
       req.headers["x-forwarded-host"]!==undefined||
       req.headers["x-forwarded-proto"]!==undefined||
       req.headers.authorization!==undefined){
      send(res,403,{error:"denied"});return;
    }
    if(req.method==="GET"&&url==="/health"){
      send(res,200,{status:"acceptance_only",registration:"inactive_only",
        activation:"disabled",
        approval:options.approval?"webauthn_review_issuer":"disabled",connector:"disabled"});
      return;
    }
    // Scope issuance is *not* an OAuth-client endpoint. The intake checks
    // Cloud's pinned Ed25519 public key and a one-use signed request before
    // it can register a review intent for an independently signed-in owner.
    if(options.approval&&req.method==="POST"&&
       url==="/internal/owner-read/intent"){
      await options.approval.receiveSignedIntent(req,res);return;
    }
    if(options.approval&&(
       (req.method==="GET"&&(
         url==="/owner-read/review.js"||
         url.startsWith("/owner-read/review?")))||
       (req.method==="POST"&&url==="/owner-read/approval")
    )){
      await options.approval.review(req,res);return;
    }
    if(req.method==="GET"&&url==="/owner-passkey/register/client.js"){
      res.writeHead(200,{"Content-Type":"text/javascript; charset=utf-8",
        "Cache-Control":"no-store","X-Content-Type-Options":"nosniff",
        "Referrer-Policy":"no-referrer"});
      res.end(options.clientScript);return;
    }
    if(url==="/owner-passkey/register"){
      await page(req,res);return;
    }
    if(url==="/owner-passkey/register/begin"||
       url==="/owner-passkey/register/complete"){
      await register(req,res);return;
    }
    const pathname=new URL(options.authorityOrigin+url).pathname;
    const permittedBrowser=pathname==="/sign-in"||pathname==="/account"||
      pathname==="/auth/start/github";
    // A separate owner authority is NOT an MCP/OAuth resource server.
    // Never expose the broader OAuth2 issuance/token/JWKS plugin routes.
    const authRoute=(
      pathname==="/api/auth/callback/github"&&req.method==="GET"
    )||(
      pathname==="/api/auth/get-session"&&req.method==="GET"
    )||(
      pathname==="/api/auth/sign-out"&&req.method==="POST"
    );
    if(!permittedBrowser&&!authRoute){
      send(res,404,{error:"not_found"});return;
    }
    const headers=new Headers();
    for(const [name,value] of Object.entries(req.headers)){
      if(typeof value==="string"&&
         !["host","connection","transfer-encoding","content-length"].includes(name))
        headers.set(name,value);
    }
    let body:Buffer|undefined;
    if(!["GET","HEAD"].includes(req.method??"GET")){
      let total=0;const chunks:Buffer[]=[];
      for await(const chunk of req){
        const bytes=Buffer.from(chunk as Uint8Array);
        total+=bytes.length;
        if(total>64_000){send(res,413,{error:"too_large"});return;}
        chunks.push(bytes);
      }
      body=Buffer.concat(chunks);
    }
    const source=new Request(options.authorityOrigin+url,{
      method:req.method??"GET",headers,
      ...(body?{body:body.toString("utf8")}:{}),redirect:"manual"
    });
    if(permittedBrowser){
      const browser=await browserResponse(source,options.identity,options.authorityOrigin);
      if(!browser){send(res,404,{error:"not_found"});return;}
      await emit(res,browser);return;
    }
    await emit(res,await options.identity.handler(source));
  };
  const server=createHttpsServer(options.tls,(req,res)=>{
    void route(req,res).catch(()=>{
      if(!res.headersSent)send(res,403,{error:"denied"});
      else res.end();
    });
  });
  server.headersTimeout=15_000;
  server.requestTimeout=20_000;
  return server;
}
