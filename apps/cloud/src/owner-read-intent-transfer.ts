import {createPrivateKey,createPublicKey,sign,verify,type KeyObject} from "node:crypto";
import {request as httpsRequest} from "node:https";
import type {IncomingMessage,ServerResponse} from "node:http";
import type {PreparedOwnerSummary} from "./connector-ws.js";
import type {OwnerReadApprovalIntent} from "./owner-read-webauthn-issuer.js";

const UUID=/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const SIGNING_CONTEXT="kicad-owner-read-intent-v1";
const INTAKE_PATH="/internal/owner-read/intent";
type SignedIntent=Readonly<{
  version:1;intent:OwnerReadApprovalIntent;signature:string;
}>;
type TrustedRegistrar={
  addTrustedIntent:(intent:OwnerReadApprovalIntent,credentialId:string)=>boolean;
};
function fixedOrigin(input:string):URL{
  const url=new URL(input);
  if(url.protocol!=="https:"||url.origin!==input||
     url.pathname!=="/"||url.username||url.password||url.search||url.hash||
     input.length>256)throw Error("Exact trusted HTTPS origin is required");
  return url;
}
function validIntent(intent:OwnerReadApprovalIntent,origin:string):boolean{
  if(!intent||!UUID.test(intent.requestId)||
     !UUID.test(intent.deviceId)||!UUID.test(intent.projectId)||
     typeof intent.ownerSub!=="string"||!intent.ownerSub||
     intent.ownerSub.length>256||
     typeof intent.clientId!=="string"||!intent.clientId||
     intent.clientId.length>1024||
     intent.origin!==origin||
     !Number.isSafeInteger(intent.expiresAtUnixMs)||
     intent.expiresAtUnixMs-Date.now()<5_000||
     intent.expiresAtUnixMs-Date.now()>30_000)return false;
  return true;
}
function canonical(intent:OwnerReadApprovalIntent):Buffer{
  return Buffer.from(JSON.stringify([
    SIGNING_CONTEXT,intent.requestId,intent.ownerSub,intent.clientId,
    intent.deviceId,intent.projectId,intent.origin,
    "project_summary",intent.expiresAtUnixMs
  ]),"utf8");
}
function keyPair(raw:string|Buffer,privateKey:boolean):KeyObject{
  const pem=Buffer.isBuffer(raw)?raw.toString("utf8"):raw;
  const expectedKind=privateKey?"PRIVATE":"PUBLIC";
  const header=["-----BEGIN",expectedKind,"KEY-----"].join(" ");
  if(!pem.startsWith(header))
    throw Error("Cloud signer and owner verifier must use distinct PEM key types");
  const key=privateKey?createPrivateKey(raw):createPublicKey(raw);
  if(key.asymmetricKeyType!=="ed25519")
    throw Error("Independent intent exchange requires Ed25519");
  return key;
}
export function createSignedOwnerIntentDelivery(
  authorityOrigin:string,cloudOrigin:string,privateKeyPem:string|Buffer,
  ca?:Buffer
){
  const target=fixedOrigin(authorityOrigin);
  fixedOrigin(cloudOrigin);
  const key=keyPair(privateKeyPem,true);
  return async (prepared:PreparedOwnerSummary):Promise<string|null>=>{
    if(prepared.operation!=="project_summary"||
       !validIntent(prepared,cloudOrigin))return null;
    const intent:OwnerReadApprovalIntent={
      requestId:prepared.requestId,ownerSub:prepared.ownerSub,
      clientId:prepared.clientId,deviceId:prepared.deviceId,
      projectId:prepared.projectId,origin:prepared.origin,
      expiresAtUnixMs:prepared.expiresAtUnixMs
    };
    const body=JSON.stringify({
      version:1,intent,
      signature:sign(null,canonical(intent),key).toString("base64url")
    } satisfies SignedIntent);
    if(body.length>4_096)return null;
    return new Promise(resolve=>{
      const req=httpsRequest({
        hostname:target.hostname,
        port:target.port||443,
        // Total wall-clock deadline, not only socket inactivity: a slow
        // streaming peer cannot hold the Cloud prepare request open.
        path:INTAKE_PATH,method:"POST",timeout:2_500,
        signal:AbortSignal.timeout(2_500),
        ...(ca?{ca}:{}),
        headers:{Host:target.host,"Content-Type":"application/json",
          "Content-Length":Buffer.byteLength(body)}
      },res=>{
        // Never follow redirects or trust response-provided URL.
        res.resume();
        res.on("error",()=>resolve(null));
        res.on("aborted",()=>resolve(null));
        res.on("end",()=>resolve(res.statusCode===204?
          authorityOrigin+"/owner-read/review?requestId="+intent.requestId:null));
      });
      req.on("timeout",()=>req.destroy());
      req.on("error",()=>resolve(null));
      req.end(body);
    });
  };
}
/**
 * Authenticated service-to-service intake for a SEPARATE owner authority.
 * A public OAuth client cannot inject an intent; its client-supplied body has
 * no trust without a valid Cloud Ed25519 signature for the exact fixed scope.
 * This handler is deliberately NOT mounted on either production service.
 */
export function createVerifiedOwnerIntentIntake(
  authorityOrigin:string,expectedCloudOrigin:string,
  cloudPublicKeyPem:string|Buffer,
  resolveActiveCredential:(ownerSub:string)=>Promise<string|null>,
  registrar:TrustedRegistrar
){
  const authority=fixedOrigin(authorityOrigin);
  fixedOrigin(expectedCloudOrigin);
  const key=keyPair(cloudPublicKeyPem,false);
  const replay=new Map<string,number>();
  return async (request:IncomingMessage,response:ServerResponse):Promise<void>=>{
    const deny=()=>{
      if(response.headersSent)return;
      response.writeHead(403,{"Cache-Control":"no-store",
        "X-Content-Type-Options":"nosniff"});
      response.end();
    };
    if(request.method!=="POST"||request.url!==INTAKE_PATH||
       request.headers.host!==authority.host||
       request.headers["content-type"]!=="application/json"||
       request.headers.authorization!==undefined||
       request.headers.cookie!==undefined||
       request.headers["x-forwarded-host"]!==undefined||
       request.headers["x-forwarded-proto"]!==undefined||
       (request.headers["sec-fetch-site"]&&
         request.headers["sec-fetch-site"]!=="same-origin")){
      deny();return;
    }
    try{
      let size=0;
      const chunks:Buffer[]=[];
      for await(const part of request){
        const data=Buffer.from(part as Uint8Array);
        size+=data.length;
        if(size>4_096){deny();return;}
        chunks.push(data);
      }
      const decoded:unknown=JSON.parse(Buffer.concat(chunks).toString("utf8"));
      if(!decoded||typeof decoded!=="object"||Array.isArray(decoded)) {
        deny();return;
      }
      const packet=decoded as Record<string,unknown>;
      if(Object.keys(packet).length!==3||
         packet.version!==1||typeof packet.signature!=="string"||
         !/^[A-Za-z0-9_-]{86}$/.test(packet.signature)||
         !packet.intent||typeof packet.intent!=="object"||
         Array.isArray(packet.intent)){
        deny();return;
      }
      const values=packet.intent as Record<string,unknown>;
      if(Object.keys(values).length!==7||
         !["requestId","ownerSub","clientId","deviceId",
           "projectId","origin","expiresAtUnixMs"].every(x=>
           Object.hasOwn(values,x))||
         !validIntent(values as OwnerReadApprovalIntent,expectedCloudOrigin)){
        deny();return;
      }
      const intent=values as OwnerReadApprovalIntent;
      const signature=Buffer.from(packet.signature,"base64url");
      if(signature.length!==64||
         !verify(null,canonical(intent),key,signature)){
        deny();return;
      }
      const now=Date.now();
      for(const [id,deadline] of replay){
        if(deadline<=now)replay.delete(id);
      }
      if(replay.size>=128||replay.has(intent.requestId)){
        deny();return;
      }
      // Claim before any async operation. Invalid or interrupted requests
      // cannot retry with the same authenticated intent.
      replay.set(intent.requestId,intent.expiresAtUnixMs);
      const credential=await resolveActiveCredential(intent.ownerSub);
      if(!credential||!registrar.addTrustedIntent(intent,credential)){
        deny();return;
      }
      response.writeHead(204,{"Cache-Control":"no-store",
        "Referrer-Policy":"no-referrer","X-Content-Type-Options":"nosniff"});
      response.end();
    }catch{deny();}
  };
}
