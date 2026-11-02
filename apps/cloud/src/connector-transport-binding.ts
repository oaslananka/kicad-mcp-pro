import type {PgConnectorSessions} from "./connector-session.js";
import type {PgConnectorReadGate,ReadGateResult,TrustedOAuthReadIdentity}
  from "./connector-read-gate.js";

export type DeviceSessionPort=Pick<PgConnectorSessions,"issue"|"activate"|"close">;
export type ReadAdmissionPort=Pick<PgConnectorReadGate,"verifySignedRead"> &
  Partial<Pick<PgConnectorReadGate,"authorizeOutgoingSummary">>;
export type AuthenticatedDevice={readonly ownerSub:string;readonly deviceId:string};
export type BoundBegin=
  |{kind:"issued";sessionId:string;challengeId:string;nonce:string;
    binding:string;expiresAtMs:number}
  |{kind:"unavailable"};

type ConnectionEntry={
  state:"opening"|"pending"|"active"|"closed";
  readonly ownerSub:string;
  readonly deviceId:string;
  sessionId?:string;
  challengeId?:string;
  nonce?:string;
  binding?:string;
};

/**
 * Only an actual server-owned transport object may be used as a key.
 * Never expose the object or this registry to untrusted HTTP arguments.
 * The caller must independently authenticate the device BEFORE begin().
 */
export class BoundConnectorConnections{
  private readonly sockets=new WeakMap<object,ConnectionEntry>();
  constructor(private readonly sessions:DeviceSessionPort,
    private readonly admission:ReadAdmissionPort){}

  async begin(socket:object,identity:AuthenticatedDevice):Promise<BoundBegin>{
    if(!socket||typeof socket!=="object"||this.sockets.has(socket)||
      !identity||typeof identity.ownerSub!=="string"||
      !identity.ownerSub||typeof identity.deviceId!=="string"){
      return {kind:"unavailable"};
    }
    const entry:ConnectionEntry={
      state:"opening",ownerSub:identity.ownerSub,deviceId:identity.deviceId
    };
    // Reserve the socket synchronously to prevent concurrent double-begin.
    this.sockets.set(socket,entry);
    try{
      const issued=await this.sessions.issue(entry.ownerSub,entry.deviceId);
      if(issued.kind!=="issued"){
        if(this.sockets.get(socket)===entry)this.sockets.delete(socket);
        return {kind:"unavailable"};
      }
      if(this.sockets.get(socket)!==entry||entry.state!=="opening"){
        // A disconnect raced the DB issue; burn the pending challenge.
        await this.sessions.close(entry.ownerSub,entry.deviceId,
          issued.sessionId,issued.binding);
        return {kind:"unavailable"};
      }
      entry.state="pending";
      entry.sessionId=issued.sessionId;
      entry.challengeId=issued.challengeId;
      entry.nonce=issued.nonce;
      entry.binding=issued.binding;
      return issued;
    }catch(error){
      if(this.sockets.get(socket)===entry)this.sockets.delete(socket);
      throw error;
    }
  }

  /** Signature is the only data taken from the untrusted peer. */
  async activate(socket:object,signature:Buffer):Promise<boolean>{
    const e=socket&&this.sockets.get(socket);
    if(!e||e.state!=="pending"||!e.sessionId||!e.nonce||!e.binding)return false;
    const result=await this.sessions.activate(e.ownerSub,e.deviceId,
      e.sessionId,e.nonce,e.binding,signature);
    if(result.kind!=="active"||this.sockets.get(socket)!==e||
      e.state!=="pending")return false;
    e.state="active";
    e.nonce=undefined;
    e.challengeId=undefined;
    return true;
  }

  /**
   * The OAuth identity MUST come from resource-server JWT verification.
   * The socket supplies all device/session/binding fields; a wire frame
   * never chooses a trusted connector context.
   */
  async admitRead(socket:object,oauth:TrustedOAuthReadIdentity,
    sequence:number,raw:Buffer,signature:Buffer):Promise<ReadGateResult>{
    const e=socket&&this.sockets.get(socket);
    if(!e||e.state!=="active"||!e.sessionId||!e.binding||
      !oauth||oauth.ownerSub!==e.ownerSub)return {kind:"unavailable"};
    const decision=await this.admission.verifySignedRead(oauth,{
      deviceId:e.deviceId,sessionId:e.sessionId,connectionBinding:e.binding
    },sequence,raw,signature);
    // Reject a result which finished after the transport disconnected.
    if(this.sockets.get(socket)!==e||e.state!=="active"){
      return {kind:"unavailable"};
    }
    return decision;
  }

  /** Server-owned socket identity; fail closed without a database gate. */
  async authorizeOutgoingSummary(socket:object,oauth:TrustedOAuthReadIdentity,
    projectId:string):Promise<boolean>{
    const e=socket&&this.sockets.get(socket);
    if(e?.state!=="active"||!e.sessionId||!e.binding||
      oauth?.ownerSub!==e.ownerSub||
      !this.admission.authorizeOutgoingSummary)return false;
    const authorized=await this.admission.authorizeOutgoingSummary(oauth,{
      deviceId:e.deviceId,sessionId:e.sessionId,connectionBinding:e.binding
    },projectId);
    return authorized&&this.sockets.get(socket)===e&&e.state==="active";
  }

  /** Disconnect is idempotent and fences the in-process socket immediately. */
  async disconnect(socket:object):Promise<void>{
    const e=socket&&this.sockets.get(socket);
    if(!e)return;
    e.state="closed";
    this.sockets.delete(socket);
    if(e.sessionId&&e.binding){
      await this.sessions.close(e.ownerSub,e.deviceId,e.sessionId,e.binding);
    }
  }
}
