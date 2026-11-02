import {randomUUID} from "node:crypto";
import type {Pool,PoolClient} from "pg";
import {PgDeviceManagement} from "./device-management.js";
import {issuePairing,reviewPairing,redeemPairing,pairingApprovalState,
  type PairingRecord,type PairingStatus} from "./device-pairing.js";

type Row={
  id:string;device_alias:string;device_public_key_der:string;device_fingerprint:string;
  user_code_mac:string;device_code_mac:string;expires_at:Date;state:PairingStatus;
  attempts:number;owner_sub:string|null;
};
export type BrowserReview="approved"|"denied"|"invalid_code"|"locked"|"unavailable";
export type Enrollment={kind:"enrolled";deviceId:string;ownerSub:string;deviceFingerprint:string}|{kind:"unavailable"};
const UUID=/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

function convert(row:Row):PairingRecord {
  return {id:row.id,deviceAlias:row.device_alias,
    devicePublicKeyDer:row.device_public_key_der,deviceFingerprint:row.device_fingerprint,
    userCodeMac:row.user_code_mac,deviceCodeMac:row.device_code_mac,
    expiresAtMs:row.expires_at.getTime(),state:row.state,
    attempts:row.attempts,ownerSub:row.owner_sub};
}
async function clock(db:Pool|PoolClient):Promise<number>{
  const r=await db.query<{ms:string}>(
    "SELECT floor(extract(epoch FROM clock_timestamp()) * 1000)::bigint AS ms");
  const now=Number(r.rows[0]?.ms);
  if(!Number.isSafeInteger(now)||now<=0)throw new Error("INVALID_DATABASE_CLOCK");
  return now;
}
async function save(db:PoolClient,r:PairingRecord):Promise<void>{
  const result=await db.query(
    "UPDATE pairing_challenges SET state=$2,attempts=$3,owner_sub=$4 WHERE id=$1",
    [r.id,r.state,r.attempts,r.ownerSub]);
  if(result.rowCount!==1)throw new Error("PAIRING_ROW_MISSING");
}

/** Isolation only: NO browser authentication, CSRF, device credentials or live routes. */
export class PgPairingChallenges {
  private readonly key:Buffer;
  constructor(private readonly pool:Pool,secret:Buffer){
    if(!Buffer.isBuffer(secret)||secret.length<32)throw new Error("PAIRING_KEY_TOO_SHORT");
    this.key=Buffer.from(secret);
  }
  async issue(alias:string,publicKeyDer:Buffer){
    const now=await clock(this.pool);
    for(let i=0;i<3;i++){
      const issued=issuePairing(this.key,now,alias,publicKeyDer);
      const r=issued.record;
      try {
        await this.pool.query(
          "INSERT INTO pairing_challenges "+
          "(id,device_alias,device_public_key_der,device_fingerprint,user_code_mac,device_code_mac,expires_at,state,attempts,owner_sub) "+
          "VALUES ($1,$2,$3,$4,$5,$6,to_timestamp($7::double precision/1000),$8,$9,$10)",
          [r.id,r.deviceAlias,r.devicePublicKeyDer,r.deviceFingerprint,
           r.userCodeMac,r.deviceCodeMac,r.expiresAtMs,r.state,r.attempts,r.ownerSub]);
        return {id:r.id,userCode:issued.userCode,deviceCode:issued.deviceCode,
          deviceFingerprint:r.deviceFingerprint,expiresAtMs:r.expiresAtMs};
      }catch(e){
        if((e as {code?:string}).code!=="23505")throw e;
      }
    }
    throw new Error("PAIRING_CODE_COLLISION");
  }
  private async locked<T>(
    id:string,fallback:T,action:(db:PoolClient,r:PairingRecord,now:number)=>Promise<T>
  ):Promise<T>{
    if(!UUID.test(id))return fallback;
    const db=await this.pool.connect();
    try{
      await db.query("BEGIN");
      const rows=await db.query<Row>(
        "SELECT id,device_alias,device_public_key_der,device_fingerprint,"+
        "user_code_mac,device_code_mac,expires_at,state,attempts,owner_sub "+
        "FROM pairing_challenges WHERE id=$1 FOR UPDATE",[id]);
      let output=fallback;
      if(rows.rows[0])output=await action(db,convert(rows.rows[0]),await clock(db));
      await db.query("COMMIT");
      return output;
    }catch(e){
      try{await db.query("ROLLBACK");}catch{/*preserve first error*/}
      throw e;
    }finally{db.release();}
  }
  /** The caller MUST independently authenticate owner, verify CSRF and throttle. */
  async review(id:string,owner:string,code:string,decision:"approve"|"deny"):Promise<BrowserReview>{
    if(!owner||owner.length>256)return "unavailable";
    return this.locked(id,"unavailable" as BrowserReview,async(db,r,now)=>{
      const result=reviewPairing(r,this.key,now,owner,code,decision);
      if(result.record.state!==r.state||result.record.attempts!==r.attempts||
        result.record.ownerSub!==r.ownerSub)await save(db,result.record);
      return result.kind;
    });
  }
  /**
   * Enroll only after browser approval and Ed25519 proof. One transaction
   * inserts the disabled device and its revocable public-key identity AND
   * consumes the challenge, so DB failure cannot burn the user's approval.
   * There is deliberately no HTTP endpoint or device execution here.
   */
  async enroll(id:string,code:string,signature:Buffer):Promise<Enrollment>{
    return this.locked(id,{kind:"unavailable"} as Enrollment,async(db,r,now)=>{
      const proof=redeemPairing(r,this.key,now,code,signature);
      if(proof.record.state!==r.state && proof.kind!=="redeemed"){
        await save(db,proof.record);
      }
      if(proof.kind!=="redeemed")return {kind:"unavailable"};
      const deviceId=randomUUID();
      await db.query(
        "INSERT INTO devices(id,owner_sub,alias,enabled) VALUES($1,$2,$3,false)",
        [deviceId,proof.ownerSub,r.deviceAlias]);
      await db.query(
        "INSERT INTO device_credentials "+
        "(device_id,owner_sub,public_key_der,key_fingerprint,pairing_challenge_id) "+
        "VALUES($1,$2,$3,$4,$5)",
        [deviceId,proof.ownerSub,r.devicePublicKeyDer,r.deviceFingerprint,r.id]);
      await save(db,proof.record);
      return {kind:"enrolled",deviceId,ownerSub:proof.ownerSub,deviceFingerprint:r.deviceFingerprint};
    });
  }

  /** Read-only; no public state enumeration without 256-bit code AND private-key proof. */
  async approved(id:string,code:string,signature:Buffer):Promise<boolean|null>{
    if(!UUID.test(id))return null;
    const rows=await this.pool.query<Row>(
      "SELECT id,device_alias,device_public_key_der,device_fingerprint,"+
      "user_code_mac,device_code_mac,expires_at,state,attempts,owner_sub "+
      "FROM pairing_challenges WHERE id=$1",[id]);
    const row=rows.rows[0];
    return row?pairingApprovalState(convert(row),this.key,await clock(this.pool),
      code,signature):null;
  }

  /** Shared transactional owner revocation implementation. */
  async revokeDevice(owner:string,id:string):Promise<boolean>{
    return new PgDeviceManagement(this.pool).revokeDevice(owner,id);
  }

  /**
   * Key lookup is intentionally fail-closed: caller MUST still prove live
   * possession with a fresh replay-protected challenge before any connection.
   */
  async activeDevicePublicKey(owner:string,id:string):Promise<Buffer|null>{
    if(!owner||owner.length>256||!UUID.test(id))return null;
    const result=await this.pool.query<{public_key_der:string}>(
      "SELECT c.public_key_der FROM devices d "+
      "JOIN device_credentials c ON c.device_id=d.id AND c.owner_sub=d.owner_sub "+
      "WHERE d.id=$1 AND d.owner_sub=$2 AND d.enabled=true AND c.revoked_at IS NULL",
      [id,owner]);
    return result.rows[0] ? Buffer.from(result.rows[0].public_key_der,"base64") : null;
  }
}
