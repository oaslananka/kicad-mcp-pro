import {createPublicKey, randomUUID, verify} from "node:crypto";
import type {Pool,PoolClient} from "pg";
import {PgDeviceManagement} from "./device-management.js";
import {issuePairing,reviewPairing,redeemPairing,pairingApprovalState,verifyFinishedRecovery,
  type PairingRecord,type PairingStatus,type RecoveryIdentity} from "./device-pairing.js";

type Row={
  id:string;device_alias:string;device_public_key_der:string;device_fingerprint:string;
  user_code_mac:string;device_code_mac:string;expires_at:Date;state:PairingStatus;
  attempts:number;owner_sub:string|null;
};
export type BrowserReview="approved"|"denied"|"invalid_code"|"locked"|"unavailable";
export type Enrollment={kind:"enrolled";deviceId:string;ownerSub:string;deviceFingerprint:string}|{kind:"unavailable"}|{kind:"recovery_denied"};
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
  private async recoveryReceipt(db:PoolClient,r:PairingRecord,
    code:string,signature:Buffer,recovery:RecoveryIdentity):Promise<Enrollment>{
    // The enrollment expiry remains enforced. This read-only lookup can
    // survive a process restart after expiry because it requires the exact
    // consumed challenge, secret, signing key and still-active replacement.
    if(!verifyFinishedRecovery(r,this.key,code,signature,recovery))return {kind:"unavailable"};
    const result=await db.query<{id:string}>(
      "SELECT d.id FROM device_replacements t "+
      "JOIN devices d ON d.id=t.replacement_device_id AND d.owner_sub=t.owner_sub "+
      "JOIN device_credentials c ON c.device_id=d.id AND c.owner_sub=d.owner_sub "+
      "WHERE t.owner_sub=$1 AND t.previous_device_id=$2 AND t.pairing_challenge_id=$3 "+
      "AND c.pairing_challenge_id=$3 AND c.key_fingerprint=$4 "+
      "AND c.public_key_der=$5 AND d.enabled=true AND c.revoked_at IS NULL",
      [recovery.ownerSub,recovery.deviceId,r.id,r.deviceFingerprint,r.devicePublicKeyDer]);
    const deviceId=result.rows[0]?.id;
    return result.rows.length===1&&deviceId
      ?{kind:"enrolled",deviceId,ownerSub:recovery.ownerSub,deviceFingerprint:r.deviceFingerprint}
      :{kind:"unavailable"};
  }

  /**
   * Enroll only after browser approval and Ed25519 proof. One transaction
   * inserts the browser-approved device with a revocable public-key identity
   * and consumes the challenge atomically. The legacy request leaves the
   * device disabled; newer clients may explicitly request connection only.
   * Neither variant grants a project or AI app any file access.
   * There is deliberately no HTTP endpoint or device execution here.
   */
  async enroll(id:string,code:string,signature:Buffer,
    connectOnApproval=false,recovery?:RecoveryIdentity):Promise<Enrollment>{
    return this.locked(id,{kind:"unavailable"} as Enrollment,async(db,r,now)=>{
      if(recovery&&connectOnApproval===true&&r.state==="consumed"){
        return this.recoveryReceipt(db,r,code,signature,recovery);
      }
      const proof=redeemPairing(r,this.key,now,code,signature,recovery);
      if(proof.record.state!==r.state && proof.kind!=="redeemed"){
        await save(db,proof.record);
      }
      if(proof.kind!=="redeemed"){
        if(recovery&&connectOnApproval===true&&proof.record.state==="expired"&&
           verifyFinishedRecovery(proof.record,this.key,code,signature,recovery)){
          return {kind:"recovery_denied"};
        }
        return {kind:"unavailable"};
      }
      if(recovery){
        // Browser approval authenticates the account. Do not disclose or
        // replace another owner's registration, or a merely disabled device.
        let permitted=connectOnApproval===true&&proof.ownerSub===recovery.ownerSub;
        if(permitted){
          const old=await db.query<{owner_sub:string}>(
            "SELECT owner_sub FROM devices WHERE id=$1 FOR UPDATE",[recovery.deviceId]);
          if(old.rows.length!==0){
            permitted=old.rows.length===1&&old.rows[0]?.owner_sub===proof.ownerSub;
            if(permitted){
              const credential=await db.query<{revoked:boolean}>(
                "SELECT (revoked_at IS NOT NULL) AS revoked FROM device_credentials "+
                "WHERE device_id=$1 AND owner_sub=$2 FOR UPDATE",[recovery.deviceId,proof.ownerSub]);
              permitted=credential.rows.length===1&&credential.rows[0]?.revoked===true;
            }
          }
        }
        if(!permitted){
          await save(db,proof.record);
          return {kind:"recovery_denied"};
        }
      }
      const deviceId=randomUUID();
      if(recovery){
        // A missing row cannot be locked. The unique transition reservation
        // also serializes distinct approvals for a missing or revoked device.
        // Reservation and credential issuance commit or roll back together.
        const reserved=await db.query(
          "INSERT INTO device_replacements "+
          "(owner_sub,previous_device_id,replacement_device_id,pairing_challenge_id) "+
          "VALUES($1,$2,$3,$4) ON CONFLICT(owner_sub,previous_device_id) DO NOTHING",
          [proof.ownerSub,recovery.deviceId,deviceId,r.id]);
        if(reserved.rowCount!==1){
          await save(db,proof.record);
          return {kind:"recovery_denied"};
        }
      }
      await db.query(
        "INSERT INTO devices(id,owner_sub,alias,enabled) VALUES($1,$2,$3,$4)",
        [deviceId,proof.ownerSub,r.deviceAlias,connectOnApproval===true]);
      await db.query(
        "INSERT INTO device_credentials "+
        "(device_id,owner_sub,public_key_der,key_fingerprint,pairing_challenge_id) "+
        "VALUES($1,$2,$3,$4,$5)",
        [deviceId,proof.ownerSub,r.devicePublicKeyDer,r.deviceFingerprint,r.id]);
      await save(db,proof.record);
      return {kind:"enrolled",deviceId,ownerSub:proof.ownerSub,deviceFingerprint:r.deviceFingerprint};
    });
  }

  /**
   * Device-signed initial project registration without manual UI copying.
   * Requires proof of possession of the enrolled device's Ed25519 private key.
   */
  async registerProject(deviceId:string,alias:string,signature:Buffer):Promise<{
    kind:"ok";projectId:string;alias:string;ownerSub:string;enabled:boolean;
  }|{kind:"unavailable"}>{
    if(!UUID.test(deviceId)||typeof alias!=="string"||
       !/^[A-Za-z0-9][A-Za-z0-9 ._-]{0,63}$/.test(alias)||
       !Buffer.isBuffer(signature)||signature.length!==64)return {kind:"unavailable"};
    const db=await this.pool.connect();
    try{
      await db.query("BEGIN");
      const cred=await db.query<{public_key_der:string;owner_sub:string;enabled:boolean}>(
        "SELECT c.public_key_der,d.owner_sub,d.enabled FROM devices d "+
        "JOIN device_credentials c ON c.device_id=d.id AND c.owner_sub=d.owner_sub "+
        "WHERE d.id=$1 AND c.revoked_at IS NULL FOR UPDATE OF d,c",[deviceId]);
      if(!cred.rows[0]){await db.query("ROLLBACK");return {kind:"unavailable"};}
      const {public_key_der,owner_sub,enabled}=cred.rows[0];
      const proof=Buffer.from("kicad-cloud-device-project-v1\0"+deviceId+"\0"+alias,"utf8");
      try{
        const key=createPublicKey({key:Buffer.from(public_key_der,"base64"),format:"der",type:"spki"});
        if(key.asymmetricKeyType!=="ed25519"||!verify(null,proof,key,signature)){
          await db.query("ROLLBACK");
          return {kind:"unavailable"};
        }
      }catch{
        await db.query("ROLLBACK");
        return {kind:"unavailable"};
      }
      if(!enabled){
        await db.query("UPDATE devices SET enabled=true WHERE id=$1",[deviceId]);
      }
      const existing=await db.query<{id:string;alias:string;enabled:boolean}>(
        "SELECT id,alias,enabled FROM projects WHERE device_id=$1 AND owner_sub=$2 AND alias=$3",[deviceId,owner_sub,alias]);
      let projectId:string;
      if(existing.rows[0]){
        projectId=existing.rows[0].id;
      }else{
        projectId=randomUUID();
        await db.query(
          "INSERT INTO projects(id,owner_sub,device_id,alias,enabled,max_mode) VALUES($1,$2,$3,$4,true,'readonly')",[projectId,owner_sub,deviceId,alias]);
      }
      await db.query(
        "INSERT INTO connector_managed_read_access(project_id,enabled) VALUES($1,true) ON CONFLICT(project_id) DO UPDATE SET enabled=true,updated_at=now()",[projectId]);
      await db.query("COMMIT");
      return {kind:"ok",projectId,alias,ownerSub:owner_sub,enabled:true};
    }catch(e){
      try{await db.query("ROLLBACK");}catch{}
      throw e;
    }finally{
      db.release();
    }
  }

  /** Read-only; no public state enumeration without 256-bit code AND private-key proof. */
  async approved(id:string,code:string,signature:Buffer):Promise<boolean|"denied"|null>{
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
