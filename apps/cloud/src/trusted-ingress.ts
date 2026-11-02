import type {IncomingMessage} from "node:http";
import {BlockList,isIP} from "node:net";

export type RequestSourceResolver=(req:IncomingMessage)=>string|null;

/** Normalize all equivalent IPv6 spellings to a single rate-limit key. */
function ipAddress(raw:string):string|null{
  if(!raw||raw.length>64||raw!==raw.trim()||/[,\s%]/.test(raw))return null;
  const kind=isIP(raw);
  if(kind===4)return raw;
  if(kind===6){
    try{
      const host=new URL("https://["+raw+"]/").hostname;
      if(!host.startsWith("[")||!host.endsWith("]"))return null;
      const ipv6=host.slice(1,-1);
      // Both dotted and hexadecimal IPv4-mapped spellings must share one key.
      const mapped=/^::ffff:([0-9a-f]{1,4}):([0-9a-f]{1,4})$/.exec(ipv6);
      if(mapped){
        const hi=Number.parseInt(mapped[1],16),lo=Number.parseInt(mapped[2],16);
        return [hi>>8,hi&255,lo>>8,lo&255].join(".");
      }
      return ipv6;
    }catch{return null;}
  }
  return null;
}

/**
 * Accept client IP only when received from an explicitly pinned, exact
 * TCP proxy address. Never fall back to untrusted forwarding headers or
 * a shared Cloudflare Tunnel peer when the header is absent.
 *
 * The pinned peer must be a private, isolated tunnel origin connection
 * whose edge overwrites CF-Connecting-IP. No CIDR/wildcard trusting.
 */
export function trustedCloudflareSource(
  rawTrustedPeers:string|undefined
):RequestSourceResolver{
  if(!rawTrustedPeers)throw new Error("TRUSTED_CLOUDFLARED_PEERS_REQUIRED");
  const provided=rawTrustedPeers.split(",").map(v=>v.trim());
  if(!provided.length||provided.length>8||provided.some(v=>!v||
    v.includes("/")||v.includes("*")))throw new Error("INVALID_TRUSTED_CLOUDFLARED_PEERS");
  const block=new BlockList();
  const unique=new Set<string>();
  for(const address of provided){
    const normalized=ipAddress(address);
    if(!normalized||normalized==="0.0.0.0"||normalized==="::"||
       unique.has(normalized))
      throw new Error("INVALID_TRUSTED_CLOUDFLARED_PEERS");
    unique.add(normalized);
    block.addAddress(normalized,isIP(normalized)===6?"ipv6":"ipv4");
  }
  return req=>{
    const peer=ipAddress(req.socket.remoteAddress??"");
    if(!peer||!block.check(peer,isIP(peer)===6?"ipv6":"ipv4"))return null;
    // Reject duplicate headers regardless of Node's coalescing behavior.
    let count=0;
    let forwarded="";
    for(let i=0;i<req.rawHeaders.length;i+=2){
      if(req.rawHeaders[i]?.toLowerCase()==="cf-connecting-ip"){
        count++;
        forwarded=req.rawHeaders[i+1]??"";
      }
    }
    if(count!==1)return null;
    const client=ipAddress(forwarded);
    if(!client||client==="0.0.0.0"||client==="::")return null;
    return client;
  };
}

/**
 * Owner-only private SSH/Tailscale ingress. The approved SSH server forwards
 * through the VPS host into Docker. Only that exact host-side TCP peer is
 * recognized; no forwarding headers are trusted. This identifies a single
 * source rate bucket, NOT a device/user or a substitute for Ed25519 pairing.
 *
 * Requires separate acceptance of reverse forwarding, owner SSH identity,
 * local-only tunnel bind and Docker host trust; enabling this with arbitrary
 * host processes or shared bridge access is not an accepted deployment.
 */
export function trustedPrivateSshSource(rawTrustedPeer:string|undefined):RequestSourceResolver{
  if(!rawTrustedPeer)throw new Error("TRUSTED_PRIVATE_SSH_PEER_REQUIRED");
  const peer=ipAddress(rawTrustedPeer);
  // A Docker bridge gateway must be a pinned private IPv4 address. Forbid
  // loopback/wildcards/CIDR/list entries and any public/global peer.
  if(!peer||rawTrustedPeer!==peer||isIP(peer)!==4||!/(?:^10\.|^192\.168\.|^172\.(?:1[6-9]|2[0-9]|3[01])\.)/.test(peer))
    throw new Error("INVALID_TRUSTED_PRIVATE_SSH_PEER");
  return req=>{
    if(ipAddress(req.socket.remoteAddress??"")!==peer)return null;
    // The host-side SSH forwarder does not emit HTTP forwarding headers.
    // Reject all such claims even though the source TCP peer is allowed.
    for(let i=0;i<req.rawHeaders.length;i+=2){
      if(["cf-connecting-ip","x-forwarded-for","forwarded","x-real-ip",
        "tailscale-user-login","tailscale-user-name"].includes(req.rawHeaders[i]?.toLowerCase()??""))
        return null;
    }
    return peer;
  };
}

/** Choose exactly one operator-accepted device ingress; never merge trust. */
export function configuredDeviceSource(env:NodeJS.ProcessEnv):RequestSourceResolver{
  const mode=env.CONNECTOR_INGRESS_MODE??"cloudflare";
  if(mode==="private_ssh"){
    if(env.TRUSTED_CLOUDFLARED_PEERS)throw new Error("AMBIGUOUS_CONNECTOR_INGRESS_TRUST");
    return trustedPrivateSshSource(env.TRUSTED_PRIVATE_SSH_PEER);
  }
  if(mode==="cloudflare"){
    if(env.TRUSTED_PRIVATE_SSH_PEER)throw new Error("AMBIGUOUS_CONNECTOR_INGRESS_TRUST");
    return trustedCloudflareSource(env.TRUSTED_CLOUDFLARED_PEERS);
  }
  throw new Error("INVALID_CONNECTOR_INGRESS_MODE");
}
