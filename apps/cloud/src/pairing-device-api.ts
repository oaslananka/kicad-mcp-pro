import {createHash,createHmac} from "node:crypto";
import type {Pool} from "pg";
import {PgPairingChallenges,type Enrollment} from "./pairing-store.js";
import {pairingServerKey} from "./pairing-review.js";

type IssueResult=Awaited<ReturnType<PgPairingChallenges["issue"]>>;
export type PairingDeviceOutcome<T>={kind:"ok";data:T}|{kind:"throttled"}|{kind:"unavailable"};
export interface PairingDevicePort {
  issue(source:string,alias:string,publicKeyDer:Buffer):Promise<PairingDeviceOutcome<IssueResult>>;
  enroll(source:string,id:string,deviceCode:string,signature:Buffer):
    Promise<PairingDeviceOutcome<Enrollment>>;
  approved(source:string,id:string,deviceCode:string,signature:Buffer):
    Promise<PairingDeviceOutcome<{approved:boolean}>>;
}
const UUID=/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
// Keep all counters saturated inside the schema's 1..41 bound.
const WINDOW_MINUTES=15;

/**
 * Public, unauthenticated device requests: consumed quotas are atomic in
 * PostgreSQL, shared by all workers. Source is the actual TCP peer, not
 * user-controlled Forwarded/X-Forwarded-For headers.
 */
export class PgPairingDeviceAPI implements PairingDevicePort {
  private readonly store:PgPairingChallenges;
  private readonly key:Buffer;
  constructor(private readonly pool:Pool,authSecret:string){
    const base=pairingServerKey(authSecret);
    this.store=new PgPairingChallenges(pool,base);
    this.key=createHmac("sha256",authSecret)
      .update("kicad-cloud-pairing-throttle-v1").digest();
  }
  private digest(domain:string,value:string):string{
    return createHmac("sha256",this.key).update(domain).update("\0").update(value).digest("hex");
  }
  private async take(domain:string,value:string,limit:number):Promise<boolean>{
    const key=this.digest(domain,value);
    const count=await this.pool.query<{attempts:number}>(
      "INSERT INTO pairing_device_budget(budget_key,window_started_at,attempts) "+
      "VALUES($1,statement_timestamp(),1) ON CONFLICT(budget_key) DO UPDATE SET "+
      "attempts=CASE WHEN pairing_device_budget.window_started_at <= "+
      "statement_timestamp()-interval '15 minutes' THEN 1 "+
      "ELSE LEAST(pairing_device_budget.attempts+1,41) END, "+
      "window_started_at=CASE WHEN pairing_device_budget.window_started_at <= "+
      "statement_timestamp()-interval '15 minutes' THEN statement_timestamp() "+
      "ELSE pairing_device_budget.window_started_at END RETURNING attempts",[key]);
    return (count.rows[0]?.attempts??42)<=limit;
  }
  async issue(source:string,alias:string,publicKeyDer:Buffer):
    Promise<PairingDeviceOutcome<IssueResult>>{
    if(!source||source.length>256||!Buffer.isBuffer(publicKeyDer)||
       publicKeyDer.length<32||publicKeyDer.length>128||
       typeof alias!=="string"||alias.length<1||alias.length>64){
      return {kind:"unavailable"};
    }
    if(!await this.take("issue-source",source,12))return {kind:"throttled"};
    const fingerprint=createHash("sha256").update(publicKeyDer).digest("hex");
    if(!await this.take("issue-key",fingerprint,3))return {kind:"throttled"};
    try{return {kind:"ok",data:await this.store.issue(alias,publicKeyDer)};}
    catch(error){
      if(error instanceof Error && /^(INVALID_DEVICE_ALIAS|INVALID_DEVICE_KEY|DEVICE_KEY_MUST_BE_ED25519)$/.test(error.message))
        return {kind:"unavailable"};
      throw error;
    }
  }
  async approved(source:string,id:string,deviceCode:string,signature:Buffer):
    Promise<PairingDeviceOutcome<{approved:boolean}>>{
    if(!source||source.length>256||typeof deviceCode!=="string"||!UUID.test(id)||deviceCode.length!==43||
       !Buffer.isBuffer(signature)||signature.length!==64)return {kind:"unavailable"};
    // Allow at most 40 checks within 15 minutes; DB counters saturate at 41.
    if(!await this.take("status-source",source,40))return {kind:"throttled"};
    if(!await this.take("status-challenge",id,40))return {kind:"throttled"};
    const approved=await this.store.approved(id,deviceCode,signature);
    return approved===null?{kind:"unavailable"}:{kind:"ok",data:{approved}};
  }
  async enroll(source:string,id:string,deviceCode:string,signature:Buffer):
    Promise<PairingDeviceOutcome<Enrollment>>{
    if(!source||source.length>256||typeof id!=="string"||!UUID.test(id)||
       typeof deviceCode!=="string"||deviceCode.length!==43||
       !Buffer.isBuffer(signature)||signature.length!==64)
      return {kind:"unavailable"};
    if(!await this.take("enroll-source",source,40))return {kind:"throttled"};
    if(!await this.take("enroll-challenge",id,8))return {kind:"throttled"};
    const result=await this.store.enroll(id,deviceCode,signature);
    return result.kind==="enrolled"?{kind:"ok",data:result}:{kind:"unavailable"};
  }
}

export const pairingDeviceBudgetWindowMinutes=WINDOW_MINUTES;
