import {createHash,createPublicKey,randomBytes,randomUUID,timingSafeEqual,verify} from "node:crypto";
import type {Pool,PoolClient} from "pg";
import {lockActiveDeviceKey,withDeviceTransaction} from "./device-db-transaction.js";

const UUID=/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const TTL_MS=60_000;
const MAX_ATTEMPTS=5;

type HandshakeRow={
  id:string;device_id:string;owner_sub:string;nonce_sha256:string;
  expires_at:Date;status:"pending"|"verified"|"expired"|"failed"|"revoked";
  failures:number;
};
export type ChallengeIssue=
  |{kind:"issued";challengeId:string;deviceId:string;nonce:string;expiresAtMs:number}
  |{kind:"unavailable"};
export type ChallengeVerification={kind:"verified";deviceId:string}|{kind:"unavailable"};

function validOwner(owner:string):boolean{
  return typeof owner==="string"&&owner.length>0&&owner.length<=256;
}
function nonceBytes(nonce:string):Buffer|null{
  if(typeof nonce!=="string"||!/^[A-Za-z0-9_-]{43}$/.test(nonce))return null;
  const bytes=Buffer.from(nonce,"base64url");
  return bytes.length===32&&bytes.toString("base64url")===nonce?bytes:null;
}
function clock(db:PoolClient):Promise<number>{
  return db.query<{ms:string}>(
    "SELECT floor(extract(epoch FROM clock_timestamp()) * 1000)::bigint AS ms"
  ).then(result=>{
    const ms=Number(result.rows[0]?.ms);
    if(!Number.isSafeInteger(ms)||ms<=0)throw new Error("INVALID_DATABASE_CLOCK");
    return ms;
  });
}

/** Exact domain and identity binding; this does not authorize an MCP operation. */
export function deviceHandshakeProof(challengeId:string,deviceId:string,nonce:string):Buffer{
  return Buffer.from("kicad-cloud-device-handshake-v1\0"+challengeId+"\0"+deviceId+"\0"+nonce,"utf8");
}

/**
 * Isolated DB primitive. No endpoint, transport session, key exchange or
 * tool execution is exposed. The caller MUST authenticate and rate-limit
 * device challenge issuance before this method can ever be wired to HTTP.
 */
export class PgDeviceHandshakes{
  constructor(private readonly pool:Pool){}

  async issue(owner:string,deviceId:string):Promise<ChallengeIssue>{
    if(!validOwner(owner)||!UUID.test(deviceId))return {kind:"unavailable"};
    return withDeviceTransaction<ChallengeIssue>(this.pool,async db=>{
      if(!await lockActiveDeviceKey(db,owner,deviceId))return {kind:"unavailable"};
      await db.query(
        "UPDATE device_handshake_challenges SET status='expired' "+
        "WHERE device_id=$1 AND owner_sub=$2 AND status='pending' "+
        "AND expires_at<=clock_timestamp()",
        [deviceId,owner]);
      const previous=await db.query(
        "SELECT id FROM device_handshake_challenges "+
        "WHERE device_id=$1 AND status='pending'",[deviceId]);
      if(previous.rowCount)return {kind:"unavailable"};
      const now=await clock(db);
      const nonce=randomBytes(32).toString("base64url");
      const challengeId=randomUUID();
      const digest=createHash("sha256").update(nonce,"utf8").digest("hex");
      await db.query(
        "INSERT INTO device_handshake_challenges "+
        "(id,device_id,owner_sub,nonce_sha256,created_at,expires_at) "+
        "VALUES($1,$2,$3,$4,to_timestamp($5::double precision/1000),"+
        "to_timestamp($6::double precision/1000))",
        [challengeId,deviceId,owner,digest,now,now+TTL_MS]);
      return {kind:"issued",challengeId,deviceId,nonce,expiresAtMs:now+TTL_MS};
    });
  }

  /**
   * Server-only cancellation of an unclaimed challenge following transport
   * disconnection. Retains device lock order shared with revocation.
   */
  async cancel(owner:string,deviceId:string,challengeId:string):Promise<boolean>{
    if(!validOwner(owner)||!UUID.test(deviceId)||!UUID.test(challengeId))return false;
    return withDeviceTransaction<boolean>(this.pool,async db=>{
      if(!await lockActiveDeviceKey(db,owner,deviceId))return false;
      const result=await db.query(
        "UPDATE device_handshake_challenges SET status='revoked' "+
        "WHERE id=$1 AND device_id=$2 AND owner_sub=$3 AND status='pending'",
        [challengeId,deviceId,owner]);
      return result.rowCount===1;
    });
  }

  /**
   * Successful result is only a one-use proof event. It does NOT create
   * a durable session, grant access to project data, or enable native tools.
   */
  async verify(
    owner:string,deviceId:string,challengeId:string,nonce:string,signature:Buffer
  ):Promise<ChallengeVerification>{
    if(!validOwner(owner)||!UUID.test(deviceId)||!UUID.test(challengeId))
      return {kind:"unavailable"};
    return withDeviceTransaction<ChallengeVerification>(this.pool,async db=>{
      const keyDer=await lockActiveDeviceKey(db,owner,deviceId);
      if(!keyDer)return {kind:"unavailable"};
      const result=await db.query<HandshakeRow>(
        "SELECT id,device_id,owner_sub,nonce_sha256,expires_at,status,failures "+
        "FROM device_handshake_challenges "+
        "WHERE id=$1 AND device_id=$2 AND owner_sub=$3 FOR UPDATE",
        [challengeId,deviceId,owner]);
      const row=result.rows[0];
      if(!row||row.status!=="pending")return {kind:"unavailable"};
      const now=await clock(db);
      if(now>=row.expires_at.getTime()){
        await db.query(
          "UPDATE device_handshake_challenges SET status='expired' WHERE id=$1",
          [row.id]);
        return {kind:"unavailable"};
      }
      const canonical=nonceBytes(nonce);
      const provided=canonical?createHash("sha256").update(nonce,"utf8").digest():null;
      const expected=Buffer.from(row.nonce_sha256,"hex");
      const validNonce=provided!==null&&
        expected.length===32&&timingSafeEqual(provided,expected);
      let validSignature=false;
      if(validNonce&&Buffer.isBuffer(signature)&&signature.length===64){
        try{
          const key=createPublicKey({
            key:Buffer.from(keyDer,"base64"),format:"der",type:"spki"
          });
          validSignature=key.asymmetricKeyType==="ed25519"&&verify(
            null,deviceHandshakeProof(challengeId,deviceId,nonce),key,signature);
        }catch{/* malformed key is denied */}
      }
      if(!validNonce||!validSignature){
        await db.query(
          "UPDATE device_handshake_challenges "+
          "SET failures=failures+1, status=CASE WHEN failures+1 >= $2 "+
          "THEN 'failed' ELSE 'pending' END WHERE id=$1",
          [row.id,MAX_ATTEMPTS]);
        return {kind:"unavailable"};
      }
      await db.query(
        "UPDATE device_handshake_challenges SET status='verified' WHERE id=$1",
        [row.id]);
      return {kind:"verified",deviceId};
    });
  }
}
