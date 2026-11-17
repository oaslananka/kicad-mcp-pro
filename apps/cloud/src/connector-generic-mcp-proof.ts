import {createHash,type KeyObject,sign} from "node:crypto";

const DOMAIN=Buffer.from("kicad-cloud-signed-mcp-tool-v1\0","utf8");
const UUID=/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const NAME=/^[a-z][a-z0-9_]{0,127}$/;
const NEVER_BRIDGE=new Set([
  "export_manufacturing_package","manufacturing_quality_gate",
  "check_design_for_manufacture"
]);
type Binding=Readonly<{
  deviceId:string;projectId:string;sessionId:string;
  sessionExpiresUnixMs:number;allowedOperations:readonly string[];
}>;

/** An offline signature is a cryptographic binding, NOT a grant by itself.
 * Callers must first hold current OAuth, project/client permission and durable
 * one-use Cloud reservation. Local owner must verify this exact request.
 */
export function createSignedGenericMcpProposal(
  candidate:unknown,binding:Binding,nowMs:number,issuerKey:KeyObject
):Buffer|null{
  if(!issuerKey||issuerKey.type!=="private"||
    issuerKey.asymmetricKeyType!=="ed25519"||!binding||
    !Number.isSafeInteger(nowMs)||!Number.isSafeInteger(binding.sessionExpiresUnixMs)||
    !binding.allowedOperations.includes("mcp_bridge")||
    typeof candidate!=="object"||candidate===null||Array.isArray(candidate))return null;
  const data=candidate as Record<string,unknown>;
  if(Object.keys(data).sort().join(",")!==[
    "argumentsJson","deadlineUnixMs","deviceId","kind","projectId",
    "requestId","sessionId","toolName","version"
  ].sort().join(",")||
    data.kind!=="connector.mcp_tool_write"||data.version!==1||
    ![data.deviceId,data.projectId,data.sessionId,data.requestId].every(
      value=>typeof value==="string"&&UUID.test(value))||
    data.deviceId!==binding.deviceId||data.projectId!==binding.projectId||
    data.sessionId!==binding.sessionId||
    !Number.isSafeInteger(data.deadlineUnixMs)||
    (data.deadlineUnixMs as number)<=nowMs||
    (data.deadlineUnixMs as number)>nowMs+10_000||
    (data.deadlineUnixMs as number)>binding.sessionExpiresUnixMs||
    typeof data.toolName!=="string"||!NAME.test(data.toolName)||
    NEVER_BRIDGE.has(data.toolName)||
    typeof data.argumentsJson!=="string"||
    Buffer.byteLength(data.argumentsJson,"utf8")>32_768)return null;
  try{
    const args=JSON.parse(data.argumentsJson) as unknown;
    if(!args||typeof args!=="object"||Array.isArray(args))return null;
    const payload=Buffer.from(JSON.stringify({
      kind:"connector.mcp_tool_write",version:1,
      requestId:data.requestId,deviceId:data.deviceId,projectId:data.projectId,
      sessionId:data.sessionId,deadlineUnixMs:data.deadlineUnixMs,
      toolName:data.toolName,
      argumentsSha256:createHash("sha256").update(data.argumentsJson,"utf8").digest("hex")
    }),"utf8");
    if(payload.length>1024)return null;
    const signature=sign(null,Buffer.concat([DOMAIN,payload]),issuerKey);
    const envelope=Buffer.from(JSON.stringify({
      kind:"connector.signed_mcp_tool",version:1,
      payload:payload.toString("base64url"),signature:signature.toString("base64url")
    }),"utf8");
    return envelope.length<=2048?envelope:null;
  }catch{
    return null;
  }
}
