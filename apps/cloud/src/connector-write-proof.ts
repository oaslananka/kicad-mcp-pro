import {KeyObject,sign} from "node:crypto";
import {MAX_WRITE_FRAME_BYTES,parseUntrustedWriteRequest} from "./connector-write-contract.js";

export const MAX_SIGNED_WRITE_PROPOSAL_BYTES=2048;
const domain=Buffer.from("kicad-cloud-signed-write-proposal-v1\0","utf8");
type Binding=Parameters<typeof parseUntrustedWriteRequest>[1];

/**
 * Offline-only matching half of the local signed-write proof verifier.
 * This is a serializer and cryptographic primitive, NOT authorization:
 * callers must establish live owner/client/project grants, the OAuth
 * projects:write scope, and a trusted authenticated device connection.
 * The receiver must pin the issuer's public key and durably reserve each
 * request exactly once before any native KiCad mutation is considered.
 *
 * Do not expose as an MCP tool or Connector route before live acceptance.
 * Signing keys must come from a protected server-only source, never from
 * untrusted commands, device responses or an externally visible config.
 */
export function createOfflineSignedWriteProposal(
  candidate:unknown,binding:Binding,nowMs:number,issuerKey:KeyObject
):Buffer|null{
  if(!(issuerKey instanceof KeyObject)||issuerKey.type!=="private"||
    issuerKey.asymmetricKeyType!=="ed25519")return null;
  const request=parseUntrustedWriteRequest(candidate,binding,nowMs);
  if(!request)return null;
  const payload=Buffer.from(JSON.stringify(request),"utf8");
  if(payload.length>MAX_WRITE_FRAME_BYTES)return null;
  let signature:Buffer;
  try{
    signature=sign(null,Buffer.concat([domain,payload]),issuerKey);
  }catch{
    return null;
  }
  if(signature.length!==64)return null;
  const envelope=Buffer.from(JSON.stringify({
    kind:"connector.signed_write_proposal",
    version:1,
    payload:payload.toString("base64url"),
    signature:signature.toString("base64url")
  }),"utf8");
  return envelope.length<=MAX_SIGNED_WRITE_PROPOSAL_BYTES?envelope:null;
}
