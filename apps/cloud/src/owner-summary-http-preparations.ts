import {createHash} from "node:crypto";
import {performance} from "node:perf_hooks";
import type {TrustedOAuthReadIdentity} from "./connector-read-gate.js";
import type {PreparedOwnerSummary} from "./connector-ws.js";

/**
 * Server-side bridge between two authenticated HTTP requests and the exact
 * opaque connector intent. The client receives the UUID, NEVER this object.
 * Its presence is not proof of owner approval; the connector must still
 * independently consume a bound WebAuthn-backed PostgreSQL receipt.
 */
export class OwnerSummaryHttpPreparations{
  private readonly pending=new Map<string,{
    intent:PreparedOwnerSummary;credentialDigest:string;ownerSub:string;clientId:string;
    deviceId:string;projectId:string;issuedAtSeconds:number;deadline:number;
  }>();
  private static digest(credential:string){
    return createHash("sha256").update(credential,"utf8").digest("hex");
  }
  prepare(
    authorizationValue:string,actor:TrustedOAuthReadIdentity,
    deviceId:string,projectId:string,
    create:()=>PreparedOwnerSummary|null
  ):PreparedOwnerSummary|null{
    const now=performance.now();
    for(const [id,entry] of this.pending){
      if(entry.deadline<=now)this.pending.delete(id);
    }
    if(this.pending.size>=128)return null;
    const intent=create();
    if(!intent||this.pending.has(intent.requestId)||
       !/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i
         .test(intent.requestId)||
       intent.ownerSub!==actor.ownerSub||intent.clientId!==actor.clientId||
       intent.deviceId!==deviceId||intent.projectId!==projectId||
       intent.operation!=="project_summary"||
       !Number.isSafeInteger(intent.expiresAtUnixMs)||
       intent.expiresAtUnixMs<=Date.now()||
       intent.expiresAtUnixMs>Date.now()+30_000)return null;
    this.pending.set(intent.requestId,{
      intent,credentialDigest:OwnerSummaryHttpPreparations.digest(authorizationValue),
      ownerSub:actor.ownerSub,clientId:actor.clientId,deviceId,projectId,
      issuedAtSeconds:actor.accessTokenIssuedAtSeconds,
      deadline:now+Math.min(30_000,Math.max(0,intent.expiresAtUnixMs-Date.now()))
    });
    return intent;
  }
  take(
    requestId:string,authorizationValue:string,actor:TrustedOAuthReadIdentity,
    deviceId:string,projectId:string
  ):PreparedOwnerSummary|null{
    const entry=this.pending.get(requestId);
    if(!entry)return null;
    // A matching request ID is a one-shot lookup, not a bearer capability.
    // Failed attempts also burn the exact record; reapproval is required.
    this.pending.delete(requestId);
    if(entry.deadline<=performance.now()||
       entry.ownerSub!==actor.ownerSub||entry.clientId!==actor.clientId||
       entry.issuedAtSeconds!==actor.accessTokenIssuedAtSeconds||
       entry.deviceId!==deviceId||entry.projectId!==projectId||
       entry.credentialDigest!==OwnerSummaryHttpPreparations.digest(authorizationValue)||
       entry.intent.expiresAtUnixMs<=Date.now())return null;
    return entry.intent;
  }
}
