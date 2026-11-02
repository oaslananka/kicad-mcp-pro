/**
 * OFFLINE REVIEW CANDIDATE, deliberately not deployed or routed.
 * This Worker must be bound only to the three exact device HTTP/WSS routes.
 * Original origin attribution and request semantics require live acceptance.
 */
const HOSTNAME="kicad-mcp-pro.oaslananka.dev";
const PATHS=new Map([
  ["/api/v1/pairing/device/challenge",{
    method:"POST",name:"challenge",source:"CHALLENGE_IP",global:"CHALLENGE_GLOBAL"
  }],
  ["/api/v1/pairing/device/redeem",{
    method:"POST",name:"redeem",source:"REDEEM_IP",global:"REDEEM_GLOBAL"
  }],
  ["/api/v1/connector/ws",{
    method:"GET",name:"wss",source:"WSS_IP",global:"WSS_GLOBAL"
  }]
]);
function canonicalIp(input){
  if(typeof input!=="string"||input.length>64||!input||
    input!==input.trim()||input.includes(",")||input.includes("%"))
    return null;
  if(!input.includes(":")){
    const parts=input.split(".");
    if(parts.length!==4||parts.some(part=>
      part.length===0||part.length>3||
      [...part].some(char=>char<"0"||char>"9")||
      Number(part)>255||String(Number(part))!==part))return null;
    return input==="0.0.0.0"?null:input;
  }
  try{
    const host=new URL("https://["+input+"]/").hostname;
    if(!host.startsWith("[")||!host.endsWith("]"))return null;
    const ip=host.slice(1,-1);
    if(!ip.includes(":")||ip==="::"||
       [...ip].some(char=>!"0123456789abcdef:.".includes(char)))return null;
    if(ip.startsWith("::ffff:")){
      const components=ip.slice(7).split(":");
      if(components.length===2&&components.every(value=>value.length>=1&&value.length<=4&&
        [...value].every(char=>"0123456789abcdef".includes(char)))){
        const hi=Number.parseInt(components[0],16);
        const lo=Number.parseInt(components[1],16);
        return [hi>>8,hi&255,lo>>8,lo&255].join(".");
      }
    }
    return ip;
  }catch{return null;}
}
function deny(status){
  return new Response(null,{
    status,
    headers:{
      "Cache-Control":"no-store",
      "Content-Security-Policy":"default-src 'none'",
      "X-Content-Type-Options":"nosniff"
    }
  });
}
export async function handleCandidate(request,env,forward){
  let parsed;
  try{parsed=new URL(request.url)}catch{return deny(400)}
  if(parsed.protocol!=="https:"||parsed.hostname!==HOSTNAME||
     parsed.port||parsed.search||parsed.hash)return deny(404);
  const route=PATHS.get(parsed.pathname);
  if(!route)return deny(404);
  if(request.method!==route.method)return deny(405);
  if(route.name==="wss"&&request.headers.get("Upgrade")?.toLowerCase()!=="websocket")
    return deny(426);
  const ip=canonicalIp(request.headers.get("CF-Connecting-IP"));
  if(!ip)return deny(403);
  const sourceLimiter=env?.[route.source],globalLimiter=env?.[route.global];
  if(typeof sourceLimiter?.limit!=="function"||
     typeof globalLimiter?.limit!=="function")return deny(503);
  try{
    // Approximate per-PoP limits only. Global binding counters are also
    // per Cloudflare location. Origin PostgreSQL quotas remain mandatory.
    const [actor,global]=await Promise.all([
      sourceLimiter.limit({key:route.name+":"+ip}),
      globalLimiter.limit({key:route.name+":all"})
    ]);
    if(actor?.success!==true||global?.success!==true)return deny(429);
  }catch{return deny(503)}
  if(typeof forward!=="function")return deny(503);
  // Do not rewrite Host, Authorization, CF-Connecting-IP or Upgrade.
  // A real Tunnel Worker subrequest may still modify source attribution:
  // this requires network acceptance before a route can be enabled.
  try{
    return await forward(request);
  }catch{
    return deny(503);
  }
}
// Only hardcoded, approved destination URLs ever reach fetch(). A client
// cannot select another scheme/host/port/path through its request URL.
function forwardKnownRoute(request){
  // This function deliberately returns a Promise (or throws synchronously).
  // handleCandidate owns the single await + fail-closed exception boundary.
  const path=new URL(request.url).pathname;
  switch(path){
    case "/api/v1/pairing/device/challenge":
      return fetch(new Request(
        "https://kicad-mcp-pro.oaslananka.dev/api/v1/pairing/device/challenge",request));
    case "/api/v1/pairing/device/redeem":
      return fetch(new Request(
        "https://kicad-mcp-pro.oaslananka.dev/api/v1/pairing/device/redeem",request));
    case "/api/v1/connector/ws":
      return fetch(new Request(
        "https://kicad-mcp-pro.oaslananka.dev/api/v1/connector/ws",request));
    default:
      return deny(404);
  }
}
export default {
  async fetch(request,env){
    return handleCandidate(request,env,forwardKnownRoute);
  }
};
