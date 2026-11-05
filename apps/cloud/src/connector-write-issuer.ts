import {createHash,createPrivateKey,createPublicKey,timingSafeEqual} from "node:crypto";
import {constants} from "node:fs";
import {open} from "node:fs/promises";
import {isAbsolute} from "node:path";
import {createOfflineSignedWriteProposal} from "./connector-write-proof.js";

type WriteBinding=Parameters<typeof createOfflineSignedWriteProposal>[1];
export type OfflineWriteProofIssuer=(
  candidate:unknown,binding:WriteBinding,nowMs:number
)=>Buffer|null;

/**
 * Offline-only protected Cloud Ed25519 issuer. A future trusted deployment
 * must explicitly provide a pinned public-key fingerprint and private file.
 * The caller must also check live owner/client/project OAuth grants, the
 * authenticated Connector and a durable one-use request reservation.
 *
 * This does not register any route, grant, key generator or write capability.
 * The private file is never returned, exported, logged or sent to the device.
 */
export async function openPinnedOfflineWriteIssuer(
  keyFilePath:string,pinnedPublicKeySha256:string
):Promise<OfflineWriteProofIssuer>{
  if(typeof keyFilePath!=="string"||!isAbsolute(keyFilePath)||
    keyFilePath.length>4096||
    typeof pinnedPublicKeySha256!=="string"||
    pinnedPublicKeySha256.length!==64||
    Buffer.from(pinnedPublicKeySha256,"hex").toString("hex")!==pinnedPublicKeySha256){
    throw Error("OFFLINE_WRITE_ISSUER_CONFIG");
  }
  // POSIX ownership and O_NOFOLLOW are mandatory; Windows cannot silently
  // use the weaker fallback semantics.
  if(typeof process.getuid!=="function"||!constants.O_NOFOLLOW){
    throw Error("OFFLINE_WRITE_ISSUER_UNTRUSTED");
  }
  let bytes:Buffer|undefined;
  try{
    const handle=await open(keyFilePath,
      constants.O_RDONLY|constants.O_NOFOLLOW|constants.O_NONBLOCK);
    try{
      const stat=await handle.stat();
      if(!stat.isFile()||stat.nlink!==1||stat.uid!==process.getuid()||
        (stat.mode&0o077)!==0||(stat.mode&0o400)===0||
        stat.size<80||stat.size>8192){
        throw Error("OFFLINE_WRITE_ISSUER_UNTRUSTED");
      }
      bytes=await handle.readFile();
    }finally{
      await handle.close();
    }
    if(bytes.length<80||bytes.length>8192||
      !bytes.toString("utf8").startsWith("-----BEGIN PRIVATE KEY-----\n")){
      throw Error("OFFLINE_WRITE_ISSUER_UNTRUSTED");
    }
    const privateKey=createPrivateKey(bytes);
    if(privateKey.type!=="private"||privateKey.asymmetricKeyType!=="ed25519"){
      throw Error("OFFLINE_WRITE_ISSUER_UNTRUSTED");
    }
    const publicDer=createPublicKey(privateKey).export({format:"der",type:"spki"}) as Buffer;
    const actual=createHash("sha256").update(publicDer).digest();
    const pinned=Buffer.from(pinnedPublicKeySha256,"hex");
    if(!timingSafeEqual(actual,pinned))throw Error("OFFLINE_WRITE_ISSUER_UNTRUSTED");
    return (candidate,binding,nowMs)=>
      createOfflineSignedWriteProposal(candidate,binding,nowMs,privateKey);
  }catch{
    // Do not leak filesystem paths, crypto parser internals or key contents.
    throw Error("OFFLINE_WRITE_ISSUER_UNTRUSTED");
  }finally{
    bytes?.fill(0);
  }
}
