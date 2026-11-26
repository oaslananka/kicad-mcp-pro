import {createPublicKey,verify} from "node:crypto";
import type {Pool} from "pg";

export type InventoryRequest=Readonly<{
  deviceId:string;ownerSub:string;projectId:string|null;nonce:string;issuedAtMs:number
}>;
export type InventoryState="unverified"|"active"|"device_disabled"|"device_revoked"|
  "project_missing"|"project_disabled";
export type InventoryStatus={nonce:string;state:InventoryState};
const UUID=/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

export function validInventoryRequest(r:InventoryRequest,now:number):boolean{
  return typeof r.deviceId==="string"&&UUID.test(r.deviceId)&&
    typeof r.ownerSub==="string"&&r.ownerSub.length>=1&&r.ownerSub.length<=256&&
    !/[\x00-\x1f\x7f]/.test(r.ownerSub)&&
    (r.projectId===null||(typeof r.projectId==="string"&&UUID.test(r.projectId)))&&
    typeof r.nonce==="string"&&/^[A-Za-z0-9_-]{43}$/.test(r.nonce)&&
    Buffer.from(r.nonce,"base64url").toString("base64url")===r.nonce&&
    Number.isSafeInteger(r.issuedAtMs)&&Math.abs(now-r.issuedAtMs)<=60_000;
}
export function deviceInventoryProof(r:InventoryRequest):Buffer{
  return Buffer.from(["kicad-cloud-device-inventory-v1",r.deviceId,r.ownerSub,
    r.projectId??"",r.nonce,String(r.issuedAtMs)].join("\0"),"utf8");
}

type InventoryRow={public_key_der:string;enabled:boolean;revoked:boolean;project_enabled:boolean|null};
function verifies(row:InventoryRow,r:InventoryRequest,signature:Buffer):boolean{
  try{
    const key=createPublicKey({key:Buffer.from(row.public_key_der,"base64"),format:"der",type:"spki"});
    return key.asymmetricKeyType==="ed25519"&&verify(null,deviceInventoryProof(r),key,signature);
  }catch{return false;}
}
function classify(row:InventoryRow,projectId:string|null):InventoryState{
  if(row.revoked)return "device_revoked";
  if(!row.enabled)return "device_disabled";
  if(projectId===null)return "active";
  if(row.project_enabled===null)return "project_missing";
  return row.project_enabled?"active":"project_disabled";
}

/** Read-only snapshot. No session, grant, enrollment or inventory mutation.
 * Unknown IDs and invalid proofs deliberately have the same result. */
export async function readDeviceInventory(pool:Pool,r:InventoryRequest,signature:Buffer):Promise<InventoryStatus>{
  const result=await pool.query<InventoryRow>(
    "SELECT c.public_key_der,d.enabled,(c.revoked_at IS NOT NULL) AS revoked,"+
    "p.enabled AS project_enabled FROM devices d JOIN device_credentials c "+
    "ON c.device_id=d.id AND c.owner_sub=d.owner_sub LEFT JOIN projects p "+
    "ON p.id=$3 AND p.device_id=d.id AND p.owner_sub=d.owner_sub "+
    "WHERE d.id=$1 AND d.owner_sub=$2",[r.deviceId,r.ownerSub,r.projectId]);
  const row=result.rows[0];
  return {nonce:r.nonce,state:row&&verifies(row,r,signature)?classify(row,r.projectId):"unverified"};
}
