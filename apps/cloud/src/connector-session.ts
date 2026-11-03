import {createHash,createPublicKey,randomBytes,randomUUID,timingSafeEqual,verify} from "node:crypto";
import type {Pool,PoolClient} from "pg";
import {lockActiveDeviceKey,withDeviceTransaction} from "./device-db-transaction.js";

const ID=/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const HASH=/^[0-9a-f]{64}$/;
const MAX_MESSAGE=8192;
type State="pending"|"active"|"closed"|"revoked"|"expired";
type SessionRow={
  id:string;handshake_id:string;device_id:string;owner_sub:string;
  connection_digest:string;expires_at:Date;state:State;last_sequence:string;
};
type ChallengeRow={
  nonce_sha256:string;expires_at:Date;status:string;failures:number;
};
type Issue={kind:"issued";sessionId:string;challengeId:string;nonce:string;binding:string;expiresAtMs:number}|{kind:"unavailable"};
type Activation={kind:"active";sessionId:string;expiresAtMs:number}|{kind:"unavailable"};
export type EventVerification={kind:"accepted";sequence:number}|{kind:"unavailable"};

function validOwner(owner:string):boolean{
  return typeof owner==="string"&&owner.length>0&&owner.length<=256;
}
function bytes32(token:string):Buffer|null{
  if(typeof token!=="string"||!/^[A-Za-z0-9_-]{43}$/.test(token))return null;
  const decoded=Buffer.from(token,"base64url");
  return decoded.length===32&&decoded.toString("base64url")===token?decoded:null;
}
function equalDigest(raw:string,stored:string):boolean{
  if(!bytes32(raw)||typeof stored!=="string"||!HASH.test(stored))return false;
  return timingSafeEqual(createHash("sha256").update(raw,"utf8").digest(),
    Buffer.from(stored,"hex"));
}
async function nowMs(db:PoolClient):Promise<number>{
  const r=await db.query<{ms:string}>(
    "SELECT floor(extract(epoch FROM clock_timestamp())*1000)::bigint AS ms");
  const n=Number(r.rows[0]?.ms);
  if(!Number.isSafeInteger(n)||n<=0)throw new Error("INVALID_DB_CLOCK");
  return n;
}

/** Connection binding must be minted and retained by the trusted transport. */
export function connectorSessionProof(
  sessionId:string,challengeId:string,deviceId:string,nonce:string,binding:string
):Buffer{
  return Buffer.from("kicad-cloud-bound-session-v1\0"+sessionId+"\0"+challengeId+
    "\0"+deviceId+"\0"+nonce+"\0"+binding,"utf8");
}

/** Signs raw metadata bytes by SHA-256: no KiCad files or tool payloads persist. */
export function connectorEventProof(
  sessionId:string,deviceId:string,binding:string,sequence:number,bytes:Buffer
):Buffer{
  if(!Number.isSafeInteger(sequence)||sequence<1||
     !Buffer.isBuffer(bytes)||bytes.length===0||bytes.length>MAX_MESSAGE)
    throw new Error("INVALID_CONNECTOR_EVENT");
  const hash=createHash("sha256").update(bytes).digest("hex");
  return Buffer.from("kicad-cloud-connector-event-v1\0"+sessionId+"\0"+
    deviceId+"\0"+binding+"\0"+sequence+"\0"+hash,"utf8");
}

/**
 * Purely a persistence/security primitive. No HTTP or WebSocket handler,
 * live TLS exporter binding, OAuth client, grant lookup or native operation.
 * owner, device and server-owned binding MUST come from trusted transport.
 */
export class PgConnectorSessions{
  constructor(private readonly pool:Pool){}

  private async row(db:PoolClient,owner:string,deviceId:string,sessionId:string):Promise<SessionRow|null>{
    const rows=await db.query<SessionRow>(
      "SELECT id,handshake_id,device_id,owner_sub,connection_digest,"+
      "expires_at,state,last_sequence FROM connector_sessions "+
      "WHERE id=$1 AND device_id=$2 AND owner_sub=$3 FOR UPDATE",
      [sessionId,deviceId,owner]);
    return rows.rows[0]??null;
  }
  private verifyEd25519(keyDer:string,payload:Buffer,signature:Buffer):boolean{
    if(!Buffer.isBuffer(signature)||signature.length!==64)return false;
    try{
      const key=createPublicKey({key:Buffer.from(keyDer,"base64"),format:"der",type:"spki"});
      return key.asymmetricKeyType==="ed25519"&&verify(null,payload,key,signature);
    }catch{return false;}
  }

  async issue(owner:string,deviceId:string):Promise<Issue>{
    if(!validOwner(owner)||!ID.test(deviceId))return {kind:"unavailable"};
    return withDeviceTransaction<Issue>(this.pool,async db=>{
      if(!await lockActiveDeviceKey(db,owner,deviceId))return {kind:"unavailable"};
      // Expire prior pending handshakes and sessions in the device lock.
      await db.query(
        "UPDATE device_handshake_challenges SET status='expired' "+
        "WHERE device_id=$1 AND status='pending' AND expires_at<=clock_timestamp()",
        [deviceId]);
      await db.query(
        "UPDATE connector_sessions SET state='expired' WHERE device_id=$1 "+
        "AND state IN ('pending','active') AND "+
        "(expires_at<=clock_timestamp() OR "+
        "(state='pending' AND NOT EXISTS(SELECT 1 FROM device_handshake_challenges h "+
        "WHERE h.id=connector_sessions.handshake_id AND h.status='pending')))",
        [deviceId]);
      const existing=await db.query("SELECT id FROM device_handshake_challenges "+
        "WHERE device_id=$1 AND status='pending'",[deviceId]);
      if(existing.rowCount)return {kind:"unavailable"};
      const another=await db.query("SELECT id FROM connector_sessions "+
        "WHERE device_id=$1 AND state IN ('pending','active')",[deviceId]);
      if(another.rowCount)return {kind:"unavailable"};
      const now=await nowMs(db);
      const challengeId=randomUUID(),sessionId=randomUUID();
      const nonce=randomBytes(32).toString("base64url");
      const binding=randomBytes(32).toString("base64url");
      const digestNonce=createHash("sha256").update(nonce).digest("hex");
      const digestBinding=createHash("sha256").update(binding).digest("hex");
      await db.query(
        "INSERT INTO device_handshake_challenges "+
        "(id,device_id,owner_sub,nonce_sha256,created_at,expires_at) "+
        "VALUES($1,$2,$3,$4,to_timestamp($5::double precision/1000),"+
        "to_timestamp($6::double precision/1000))",
        [challengeId,deviceId,owner,digestNonce,now,now+60_000]);
      await db.query(
        "INSERT INTO connector_sessions "+
        "(id,device_id,owner_sub,handshake_id,connection_digest,created_at,expires_at) "+
        "VALUES($1,$2,$3,$4,$5,to_timestamp($6::double precision/1000),"+
        "to_timestamp($7::double precision/1000))",
        [sessionId,deviceId,owner,challengeId,digestBinding,now,now+300_000]);
      return {kind:"issued",sessionId,challengeId,nonce,binding,expiresAtMs:now+60_000};
    });
  }

  async activate(
    owner:string,deviceId:string,sessionId:string,nonce:string,
    binding:string,signature:Buffer
  ):Promise<Activation>{
    if(!validOwner(owner)||!ID.test(deviceId)||!ID.test(sessionId))
      return {kind:"unavailable"};
    return withDeviceTransaction<Activation>(this.pool,async db=>{
      const keyDer=await lockActiveDeviceKey(db,owner,deviceId);
      if(!keyDer)return {kind:"unavailable"};
      const session=await this.row(db,owner,deviceId,sessionId);
      if(!session||session.state!=="pending")return {kind:"unavailable"};
      const challenge=await db.query<ChallengeRow>(
        "SELECT nonce_sha256,expires_at,status,failures "+
        "FROM device_handshake_challenges WHERE id=$1 AND device_id=$2 "+
        "AND owner_sub=$3 FOR UPDATE",
        [session.handshake_id,deviceId,owner]);
      const h=challenge.rows[0];
      if(!h||h.status!=="pending")return {kind:"unavailable"};
      const now=await nowMs(db);
      if(now>=h.expires_at.getTime()||now>=session.expires_at.getTime()){
        await db.query("UPDATE device_handshake_challenges SET status='expired' WHERE id=$1",
          [session.handshake_id]);
        await db.query("UPDATE connector_sessions SET state='expired' WHERE id=$1",[sessionId]);
        return {kind:"unavailable"};
      }
      const valid=equalDigest(nonce,h.nonce_sha256)&&
        equalDigest(binding,session.connection_digest)&&
        this.verifyEd25519(keyDer,connectorSessionProof(
          sessionId,session.handshake_id,deviceId,nonce,binding),signature);
      if(!valid){
        await db.query("UPDATE device_handshake_challenges SET failures=failures+1,"+
          "status=CASE WHEN failures+1>=5 THEN 'failed' ELSE 'pending' END "+
          "WHERE id=$1",[session.handshake_id]);
        if(h.failures+1>=5)await db.query(
          "UPDATE connector_sessions SET state='closed' WHERE id=$1",[sessionId]);
        return {kind:"unavailable"};
      }
      await db.query("UPDATE device_handshake_challenges SET status='verified' "+
        "WHERE id=$1",[session.handshake_id]);
      await db.query("UPDATE connector_sessions SET state='active' WHERE id=$1",[sessionId]);
      return {kind:"active",sessionId,expiresAtMs:session.expires_at.getTime()};
    });
  }

  async verifyEvent(
    owner:string,deviceId:string,sessionId:string,binding:string,
    sequence:number,bytes:Buffer,signature:Buffer
  ):Promise<EventVerification>{
    if(!validOwner(owner)||!ID.test(deviceId)||!ID.test(sessionId)||
       !Number.isSafeInteger(sequence)||sequence<1||
       !Buffer.isBuffer(bytes)||bytes.length===0||bytes.length>MAX_MESSAGE)
      return {kind:"unavailable"};
    return withDeviceTransaction<EventVerification>(this.pool,async db=>{
      const keyDer=await lockActiveDeviceKey(db,owner,deviceId);
      if(!keyDer)return {kind:"unavailable"};
      const session=await this.row(db,owner,deviceId,sessionId);
      if(!session||session.state!=="active")return {kind:"unavailable"};
      const now=await nowMs(db);
      if(now>=session.expires_at.getTime()){
        await db.query("UPDATE connector_sessions SET state='expired' WHERE id=$1",[sessionId]);
        return {kind:"unavailable"};
      }
      const expected=Number(session.last_sequence);
      if(!Number.isSafeInteger(expected)||sequence!==expected+1||
         !equalDigest(binding,session.connection_digest))return {kind:"unavailable"};
      if(!this.verifyEd25519(keyDer,connectorEventProof(
        sessionId,deviceId,binding,sequence,bytes),signature))return {kind:"unavailable"};
      await db.query("UPDATE connector_sessions SET last_sequence=$2 WHERE id=$1",
        [sessionId,sequence]);
      return {kind:"accepted",sequence};
    });
  }

  /** In-process disconnect hook; never grant access based on binding alone. */
  async close(owner:string,deviceId:string,sessionId:string,binding:string):Promise<boolean>{
    if(!validOwner(owner)||!ID.test(deviceId)||!ID.test(sessionId))return false;
    return withDeviceTransaction<boolean>(this.pool,async db=>{
      if(!await lockActiveDeviceKey(db,owner,deviceId))return false;
      const session=await this.row(db,owner,deviceId,sessionId);
      if(!session||!["pending","active"].includes(session.state)||
         !equalDigest(binding,session.connection_digest))return false;
      await db.query("UPDATE connector_sessions SET state='closed' WHERE id=$1",[sessionId]);
      if(session.state==="pending"){
        await db.query("UPDATE device_handshake_challenges SET status='revoked' "+
          "WHERE id=$1 AND status='pending'",[session.handshake_id]);
      }
      return true;
    });
  }
}
