import {constants} from "node:fs";
import {open,readFile} from "node:fs/promises";
import {createSignedOwnerIntentDelivery} from "./owner-read-intent-transfer.js";

/** Opt-in Cloud-to-independent-owner delivery. Never provisions a credential. */
export async function openConfiguredOwnerIntentDelivery(
  env:NodeJS.ProcessEnv,cloudOrigin:string,
  prerequisites:{wsEnabled:boolean;ownerConsentEnabled:boolean;identityEnabled:boolean}
){
  const enabled=env.OWNER_READ_INTENT_DELIVERY_ENABLED;
  if(enabled===undefined||enabled==="false")return null;
  if(enabled!=="true")throw Error("Invalid owner-intent delivery setting");
  if(!prerequisites.wsEnabled||!prerequisites.ownerConsentEnabled||
     !prerequisites.identityEnabled)
    throw Error("Owner-intent delivery requires identity, WSS and independent receipt consumer");
  const authorityOrigin=env.OWNER_READ_INTENT_DELIVERY_ORIGIN;
  const keyPath=env.OWNER_READ_INTENT_DELIVERY_SIGNING_KEY_FILE;
  if(!authorityOrigin||!keyPath||authorityOrigin===cloudOrigin)
    throw Error("Independent owner-intent origin and signing key are required");
  const target=new URL(authorityOrigin);
  if(target.protocol!=="https:"||target.origin!==authorityOrigin||
     target.username||target.password||target.search||target.hash||
     target.pathname!=="/")
    throw Error("Exact independent owner HTTPS origin required");
  if(typeof process.getuid!=="function")
    throw Error("Owner-intent delivery requires POSIX file identity");
  // Open the explicitly configured private key with no-follow and nonblocking
  // semantics: symlinks, FIFOs, hard links and non-owner permissions fail closed.
  const handle=await open(keyPath,constants.O_RDONLY|constants.O_NOFOLLOW|constants.O_NONBLOCK);
  let signingKey:Buffer;
  try{
    const stat=await handle.stat();
    if(!stat.isFile()||stat.nlink!==1||stat.uid!==process.getuid()||
       (stat.mode&0o077)!==0||stat.size<32||stat.size>8192)
      throw Error("Untrusted owner-intent signing key file");
    signingKey=await handle.readFile();
  }finally{
    await handle.close();
  }
  const caPath=env.OWNER_READ_INTENT_DELIVERY_CA_FILE;
  const ca=caPath?await readFile(caPath):undefined;
  if(ca&&(!ca.length||ca.length>65536))
    throw Error("Invalid owner-intent authority CA bundle");
  return createSignedOwnerIntentDelivery(authorityOrigin,cloudOrigin,signingKey,ca);
}
