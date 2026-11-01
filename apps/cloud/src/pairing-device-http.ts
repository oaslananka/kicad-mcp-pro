import type {IncomingMessage,ServerResponse} from "node:http";
import {z} from "zod";
import type {PairingDevicePort} from "./pairing-device-api.js";
import type {RequestSourceResolver} from "./trusted-ingress.js";

const issueSchema=z.strictObject({
  alias:z.string().min(1).max(64),
  publicKeyDer:z.string().min(44).max(192).regex(/^[A-Za-z0-9+/]+={0,2}$/)
});
const statusSchema=z.strictObject({
  challengeId:z.uuid(),
  deviceCode:z.string().regex(/^[A-Za-z0-9_-]{43}$/),
  signature:z.string().regex(/^[A-Za-z0-9_-]{86}$/)
});
const redeemSchema=z.strictObject({
  challengeId:z.uuid(),
  deviceCode:z.string().regex(/^[A-Za-z0-9_-]{43}$/),
  signature:z.string().regex(/^[A-Za-z0-9_-]{86}$/)
});
function reply(res:ServerResponse,code:number,data:object):void{
  res.writeHead(code,{"Content-Type":"application/json; charset=utf-8",
    "Cache-Control":"no-store","Referrer-Policy":"no-referrer",
    "X-Content-Type-Options":"nosniff","Pragma":"no-cache",
    "Content-Security-Policy":"default-src 'none'"});
  res.end(JSON.stringify(data));
}
function canonicalB64(encoded:string):Buffer|null{
  const buffer=Buffer.from(encoded,"base64");
  return buffer.toString("base64")===encoded?buffer:null;
}
function canonicalUrlB64(encoded:string,length:number):Buffer|null{
  const buffer=Buffer.from(encoded,"base64url");
  return buffer.length===length&&buffer.toString("base64url")===encoded?buffer:null;
}
async function jsonBody(req:IncomingMessage):Promise<unknown>{
  let count=0;
  const chunks:Buffer[]=[];
  for await(const raw of req){
    const chunk=Buffer.isBuffer(raw)?raw:Buffer.from(raw);
    count+=chunk.length;
    if(count>1024)throw new Error("BODY_LIMIT");
    chunks.push(chunk);
  }
  if(count===0)throw new Error("EMPTY_BODY");
  return JSON.parse(Buffer.concat(chunks).toString("utf8")) as unknown;
}

/**
 * Feature-gated, device-initiated challenge and redeem only.
 * No browser, bearer tokens, proxy-asserted IPs, local files or tool calls.
 */
export async function handlePairingDeviceRequest(
  req:IncomingMessage,res:ServerResponse,api:PairingDevicePort,
  sourceOf:RequestSourceResolver,publicOrigin?:string
):Promise<boolean>{
  const path=(req.url??"").split("?")[0];
  if(path!=="/api/v1/pairing/device/challenge"&&
     path!=="/api/v1/pairing/device/status"&&
     path!=="/api/v1/pairing/device/redeem")return false;
  if(req.method!=="POST"){reply(res,405,{error:"method_not_allowed"});return true;}
  if(req.url!==path||req.headers.origin!==undefined||
     req.headers.cookie!==undefined||req.headers.authorization!==undefined||
     req.headers["sec-fetch-site"]!==undefined){
    reply(res,403,{error:"not_permitted"});return true;
  }
  const ct=req.headers["content-type"];
  if(typeof ct!=="string"||ct!=="application/json"){
    reply(res,415,{error:"unsupported_media_type"});return true;
  }
  // Require a verified Cloudflare Tunnel peer, never X-Forwarded-For
  // or an unverified, shared proxy TCP source address.
  const source=sourceOf(req);
  if(!source){reply(res,403,{error:"untrusted_ingress"});return true;}
  let parsed:unknown;
  try{parsed=await jsonBody(req);}
  catch(error){
    reply(res,error instanceof Error&&error.message==="BODY_LIMIT"?413:400,
      {error:"invalid_request"});return true;
  }
  if(path.endsWith("/challenge")){
    const fields=issueSchema.safeParse(parsed);
    if(!fields.success){reply(res,400,{error:"invalid_request"});return true;}
    const publicKey=canonicalB64(fields.data.publicKeyDer);
    if(!publicKey){reply(res,400,{error:"invalid_request"});return true;}
    const result=await api.issue(source,fields.data.alias,publicKey);
    if(result.kind==="throttled"){reply(res,429,{error:"rate_limited"});return true;}
    if(result.kind!=="ok"){reply(res,400,{error:"unavailable"});return true;}
    reply(res,201,{challengeId:result.data.id,userCode:result.data.userCode,
      deviceCode:result.data.deviceCode,deviceFingerprint:result.data.deviceFingerprint,
      expiresAtMs:result.data.expiresAtMs,
      ...(publicOrigin?{verificationUriComplete:publicOrigin+"/devices/pairing#challenge="+
        encodeURIComponent(result.data.id)+"&code="+encodeURIComponent(result.data.userCode)}:{})});return true;
  }
  if(path.endsWith("/status")){
    const fields=statusSchema.safeParse(parsed);
    if(!fields.success){reply(res,400,{error:"invalid_request"});return true;}
    const secret=canonicalUrlB64(fields.data.deviceCode,32);
    const signature=canonicalUrlB64(fields.data.signature,64);
    if(!secret||!signature){reply(res,400,{error:"invalid_request"});return true;}
    const result=await api.approved(source,fields.data.challengeId,
      fields.data.deviceCode,signature);
    if(result.kind==="throttled"){reply(res,429,{error:"rate_limited"});return true;}
    if(result.kind!=="ok"){reply(res,400,{error:"unavailable"});return true;}
    reply(res,200,{approved:result.data.approved});return true;
  }
  const fields=redeemSchema.safeParse(parsed);
  if(!fields.success){reply(res,400,{error:"invalid_request"});return true;}
  const secret=canonicalUrlB64(fields.data.deviceCode,32);
  const sig=canonicalUrlB64(fields.data.signature,64);
  if(!secret||!sig){reply(res,400,{error:"invalid_request"});return true;}
  const result=await api.enroll(source,fields.data.challengeId,fields.data.deviceCode,sig);
  if(result.kind==="throttled"){reply(res,429,{error:"rate_limited"});return true;}
  if(result.kind!=="ok"||result.data.kind!=="enrolled"){
    reply(res,400,{error:"unavailable"});return true;
  }
  reply(res,200,{deviceId:result.data.deviceId,deviceFingerprint:result.data.deviceFingerprint,
    enabled:false});return true;
}
