import {createHash} from "node:crypto";
import type {Pool} from "pg";
import {PgPairingChallenges,type Enrollment} from "./pairing-store.js";
import {type RecoveryIdentity,validRecoveryIdentity} from "./device-pairing.js";
import {readDeviceInventory,validInventoryRequest,type InventoryRequest,type InventoryStatus} from "./device-inventory-status.js";
import {pairingServerKey} from "./pairing-review.js";
import {PgPairingBudget} from "./pairing-budget.js";

type IssueResult=Awaited<ReturnType<PgPairingChallenges["issue"]>>;
export type PairingDeviceOutcome<T>={kind:"ok";data:T}|{kind:"throttled"}|{kind:"unavailable"};
export type RegisteredProject={projectId:string;alias:string;ownerSub:string;enabled:boolean};
export interface PairingDevicePort {
  issue(source:string,alias:string,publicKeyDer:Buffer):Promise<PairingDeviceOutcome<IssueResult>>;
  enroll(source:string,id:string,deviceCode:string,signature:Buffer,
    connectOnApproval?:boolean,recovery?:RecoveryIdentity,resumeInitial?:boolean):Promise<PairingDeviceOutcome<Enrollment>>;
  approved(source:string,id:string,deviceCode:string,signature:Buffer):
    Promise<PairingDeviceOutcome<{approved:boolean;denied?:true}>>;
  inventoryStatus?(source:string,request:InventoryRequest,signature:Buffer):Promise<PairingDeviceOutcome<InventoryStatus>>;
  registerProject?(source:string,deviceId:string,alias:string,signature:Buffer):
    Promise<PairingDeviceOutcome<RegisteredProject>>;
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
  private readonly budget:PgPairingBudget;
  constructor(private readonly pool:Pool,authSecret:string){
    const base=pairingServerKey(authSecret);
    this.store=new PgPairingChallenges(pool,base);
    this.budget=new PgPairingBudget(pool,authSecret);
  }
  async issue(source:string,alias:string,publicKeyDer:Buffer):
    Promise<PairingDeviceOutcome<IssueResult>>{
    if(!source||source.length>256||!Buffer.isBuffer(publicKeyDer)||
       publicKeyDer.length<32||publicKeyDer.length>128||
       typeof alias!=="string"||alias.length<1||alias.length>64){
      return {kind:"unavailable"};
    }
    if(!await this.budget.take("issue-source",source,12))return {kind:"throttled"};
    const fingerprint=createHash("sha256").update(publicKeyDer).digest("hex");
    if(!await this.budget.take("issue-key",fingerprint,3))return {kind:"throttled"};
    try{return {kind:"ok",data:await this.store.issue(alias,publicKeyDer)};}
    catch(error){
      if(error instanceof Error && /^(INVALID_DEVICE_ALIAS|INVALID_DEVICE_KEY|DEVICE_KEY_MUST_BE_ED25519)$/.test(error.message))
        return {kind:"unavailable"};
      throw error;
    }
  }
  async approved(source:string,id:string,deviceCode:string,signature:Buffer):
    Promise<PairingDeviceOutcome<{approved:boolean;denied?:true}>>{
    if(!source||source.length>256||typeof deviceCode!=="string"||!UUID.test(id)||deviceCode.length!==43||
       !Buffer.isBuffer(signature)||signature.length!==64)return {kind:"unavailable"};
    // Allow at most 40 checks within 15 minutes; DB counters saturate at 41.
    if(!await this.budget.take("status-source",source,40))return {kind:"throttled"};
    if(!await this.budget.take("status-challenge",id,40))return {kind:"throttled"};
    const approved=await this.store.approved(id,deviceCode,signature);
    if(approved===null)return {kind:"unavailable"};
    // Only the device proving BOTH its secret and key can see denial.
    if(approved==="denied")return {kind:"ok",data:{approved:false,denied:true}};
    return {kind:"ok",data:{approved}};
  }
  async enroll(source:string,id:string,deviceCode:string,signature:Buffer,
    connectOnApproval=false,recovery?:RecoveryIdentity,resumeInitial=false):Promise<PairingDeviceOutcome<Enrollment>>{
    if(!source||source.length>256||typeof id!=="string"||!UUID.test(id)||
       typeof deviceCode!=="string"||deviceCode.length!==43||
       !Buffer.isBuffer(signature)||signature.length!==64)
      return {kind:"unavailable"};
    if(resumeInitial&&(recovery||!connectOnApproval))return {kind:"unavailable"};
    if(recovery&&(!connectOnApproval||!validRecoveryIdentity(recovery)))return {kind:"unavailable"};
    if(!await this.budget.take("enroll-source",source,40))return {kind:"throttled"};
    if(!await this.budget.take("enroll-challenge",id,8))return {kind:"throttled"};
    const result=await this.store.enroll(id,deviceCode,signature,connectOnApproval,recovery,resumeInitial);
    return result.kind!=="unavailable"?{kind:"ok",data:result}:{kind:"unavailable"};
  }
  async inventoryStatus(source:string,request:InventoryRequest,signature:Buffer):
    Promise<PairingDeviceOutcome<InventoryStatus>>{
    if(!source||source.length>256||!validInventoryRequest(request,Date.now())||
       !Buffer.isBuffer(signature)||signature.length!==64)return {kind:"unavailable"};
    if(!await this.budget.take("inventory-source",source,40))return {kind:"throttled"};
    return {kind:"ok",data:await readDeviceInventory(this.pool,request,signature)};
  }
  async registerProject(source:string,deviceId:string,alias:string,signature:Buffer):
    Promise<PairingDeviceOutcome<RegisteredProject>>{
    if(!source||source.length>256||typeof deviceId!=="string"||!UUID.test(deviceId)||
       typeof alias!=="string"||alias.length<1||alias.length>64||
       !Buffer.isBuffer(signature)||signature.length!==64)
      return {kind:"unavailable"};
    if(!await this.budget.take("project-source",source,40))return {kind:"throttled"};
    if(!await this.budget.take("project-device",deviceId,20))return {kind:"throttled"};
    const result=await this.store.registerProject(deviceId,alias,signature);
    return result.kind==="ok"?{kind:"ok",data:result}:{kind:"unavailable"};
  }
}

export const pairingDeviceBudgetWindowMinutes=WINDOW_MINUTES;
