import {createHash,createPublicKey,timingSafeEqual,verify} from "node:crypto";
import type {Pool} from "pg";
import {parseBoundReadRequest,type ConnectorReadRequest,type ReadOperation} from "./connector-protocol.js";
import {lockActiveDeviceKey,withDeviceTransaction} from "./device-db-transaction.js";

const UUID=/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const MAX_BYTES=8192;
// Signed incoming read-proof validation remains metadata-only; the distinct,
// default-OFF owner-foreground DRC count pilot reuses the trusted server-side
// outgoing project/session authorization check and has its own fixed wire kind.
// ERC and untrusted/native incoming operations remain blocked.
const READ_OPERATIONS:readonly ReadOperation[]=["project_summary"];
type SessionRow={expires_at:Date;state:string;last_sequence:string;connection_digest:string};
type GrantRow={project_enabled:boolean;grant_enabled:boolean;project_mode:string;grant_mode:string};
type CutoffRow={revoked_at:Date};
export type TrustedOAuthReadIdentity={
  readonly ownerSub:string;
  readonly clientId:string;
  readonly accessTokenIssuedAtSeconds:number;
};
export type TrustedConnectorContext={
  readonly deviceId:string;
  readonly sessionId:string;
  readonly connectionBinding:string;
};
export type ReadGateResult=
  |{kind:"accepted";request:ConnectorReadRequest;sequence:number}
  |{kind:"unavailable"};

function validIdentity(o:TrustedOAuthReadIdentity,c:TrustedConnectorContext):boolean{
  return !!o&&!!c&&typeof o.ownerSub==="string"&&o.ownerSub.length>0&&
    o.ownerSub.length<=256&&typeof o.clientId==="string"&&
    o.clientId.length>0&&o.clientId.length<=1024&&
    Number.isSafeInteger(o.accessTokenIssuedAtSeconds)&&
    o.accessTokenIssuedAtSeconds>0&&UUID.test(c.deviceId)&&UUID.test(c.sessionId);
}
function isBindingMatch(binding:string,hex:string):boolean{
  if(typeof binding!=="string"||!/^[A-Za-z0-9_-]{43}$/.test(binding)||
    typeof hex!=="string"||!/^[a-f0-9]{64}$/.test(hex))return false;
  const bytes=Buffer.from(binding,"base64url");
  if(bytes.length!==32||bytes.toString("base64url")!==binding)return false;
  return timingSafeEqual(createHash("sha256").update(binding,"utf8").digest(),Buffer.from(hex,"hex"));
}

/**
 * Domain-specific signature binds exact wire bytes, owner, AI client,
 * session, device, non-exported connection binding and ordered sequence.
 */
export function signedReadProof(
  oauth:TrustedOAuthReadIdentity,connection:TrustedConnectorContext,
  sequence:number,raw:Buffer
):Buffer{
  if(!Number.isSafeInteger(sequence)||sequence<1||
     !Buffer.isBuffer(raw)||raw.length===0||raw.length>MAX_BYTES){
    throw new Error("INVALID_SIGNED_READ");
  }
  return Buffer.from("kicad-cloud-authorized-read-v1\0"+
    oauth.ownerSub+"\0"+oauth.clientId+"\0"+connection.deviceId+"\0"+
    connection.sessionId+"\0"+connection.connectionBinding+"\0"+
    sequence+"\0"+createHash("sha256").update(raw).digest("hex"),"utf8");
}

/**
 * No network endpoint or KiCad operation is exposed. Every argument of
 * TrustedOAuthReadIdentity and TrustedConnectorContext MUST be supplied
 * by independently verified middleware and server-owned socket state.
 * The returned request is a preflight result, never an execution ticket.
 */
export class PgConnectorReadGate{
  constructor(private readonly pool:Pool){}

  /**
   * Server-originated read preflight; identity MUST come from a verified
   * OAuth JWT. Recheck immediately after receiving the local result.
   * No socket data or supplied client ID can mint these trusted inputs.
   */
  async authorizeOutgoingSummary(
    oauth:TrustedOAuthReadIdentity,connection:TrustedConnectorContext,
    projectId:string
  ):Promise<boolean>{
    if(!validIdentity(oauth,connection)||!UUID.test(projectId)||
      typeof connection.connectionBinding!=="string"||
      !/^[A-Za-z0-9_-]{43}$/.test(connection.connectionBinding))return false;
    return withDeviceTransaction(this.pool,async db=>{
      if(!await lockActiveDeviceKey(db,oauth.ownerSub,connection.deviceId))return false;
      const active=await db.query<SessionRow>(
        "SELECT expires_at,state,last_sequence,connection_digest "+
        "FROM connector_sessions WHERE id=$1 AND owner_sub=$2 AND device_id=$3 FOR UPDATE",
        [connection.sessionId,oauth.ownerSub,connection.deviceId]);
      const session=active.rows[0];
      if(!session||session.state!=="active"||
        !isBindingMatch(connection.connectionBinding,session.connection_digest))return false;
      const now=await db.query<{ms:string}>(
        "SELECT floor(extract(epoch FROM clock_timestamp())*1000)::bigint AS ms");
      const nowMs=Number(now.rows[0]?.ms);
      if(!Number.isSafeInteger(nowMs)||nowMs<=0||nowMs>=session.expires_at.getTime()||
        oauth.accessTokenIssuedAtSeconds*1000>nowMs+60_000)return false;
      const cutoff=await db.query<CutoffRow>(
        "SELECT revoked_at FROM client_token_cutoffs WHERE owner_sub=$1 "+
        "AND client_id=$2 FOR SHARE",[oauth.ownerSub,oauth.clientId]);
      if(cutoff.rows[0]&&
        oauth.accessTokenIssuedAtSeconds*1000<=cutoff.rows[0].revoked_at.getTime()){
        return false;
      }
      const grants=await db.query<GrantRow>(
        "SELECT p.enabled AS project_enabled,g.enabled AS grant_enabled,"+
        "p.max_mode AS project_mode,g.max_mode AS grant_mode FROM projects p "+
        "JOIN project_client_grants g ON g.project_id=p.id AND g.owner_sub=p.owner_sub "+
        "WHERE p.id=$1 AND p.device_id=$2 AND p.owner_sub=$3 AND g.client_id=$4 "+
        "FOR SHARE OF p,g",
        [projectId,connection.deviceId,oauth.ownerSub,oauth.clientId]);
      const grant=grants.rows[0];
      return !!grant&&grant.project_enabled&&grant.grant_enabled&&
        ["readonly","write","manufacturing"].includes(grant.project_mode)&&
        ["readonly","write","manufacturing"].includes(grant.grant_mode);
    });
  }

  async verifySignedRead(
    oauth:TrustedOAuthReadIdentity,connection:TrustedConnectorContext,
    sequence:number,raw:Buffer,signature:Buffer
  ):Promise<ReadGateResult>{
    if(!validIdentity(oauth,connection)||!Number.isSafeInteger(sequence)||sequence<1||
      !Buffer.isBuffer(raw)||raw.length===0||raw.length>MAX_BYTES||
      !Buffer.isBuffer(signature)||signature.length!==64||
      !isBindingMatch(connection.connectionBinding,createHash("sha256")
        .update(connection.connectionBinding).digest("hex"))){
      return {kind:"unavailable"};
    }
    return withDeviceTransaction<ReadGateResult>(this.pool,async db=>{
      const publicKeyDer=await lockActiveDeviceKey(db,oauth.ownerSub,connection.deviceId);
      if(!publicKeyDer)return {kind:"unavailable"};
      const result=await db.query<SessionRow>(
        "SELECT expires_at,state,last_sequence,connection_digest "+
        "FROM connector_sessions WHERE id=$1 AND device_id=$2 AND owner_sub=$3 FOR UPDATE",
        [connection.sessionId,connection.deviceId,oauth.ownerSub]);
      const session=result.rows[0];
      if(session?.state!=="active"||
        !isBindingMatch(connection.connectionBinding,session.connection_digest)){
        return {kind:"unavailable"};
      }
      const timestamp=await db.query<{ms:string}>(
        "SELECT floor(extract(epoch FROM clock_timestamp())*1000)::bigint AS ms");
      const now=Number(timestamp.rows[0]?.ms);
      if(!Number.isSafeInteger(now)||now<=0||now>=session.expires_at.getTime()||
        oauth.accessTokenIssuedAtSeconds*1000>now+60_000)return {kind:"unavailable"};
      const previous=Number(session.last_sequence);
      if(!Number.isSafeInteger(previous)||previous<0||sequence!==previous+1){
        return {kind:"unavailable"};
      }
      try{
        const key=createPublicKey({key:Buffer.from(publicKeyDer,"base64"),format:"der",type:"spki"});
        if(key.asymmetricKeyType!=="ed25519"||!verify(
          null,signedReadProof(oauth,connection,sequence,raw),key,signature)){
          return {kind:"unavailable"};
        }
      }catch{return {kind:"unavailable"};}

      // Acquire the cutoff lock BEFORE any per-client grant lock, matching
      // client revocation's cutoff -> grant order (no deadlock inversion).
      const cutoff=await db.query<CutoffRow>(
        "SELECT revoked_at FROM client_token_cutoffs WHERE owner_sub=$1 "+
        "AND client_id=$2 FOR SHARE",[oauth.ownerSub,oauth.clientId]);
      const boundary=cutoff.rows[0]?.revoked_at;
      if(boundary&&oauth.accessTokenIssuedAtSeconds*1000<=boundary.getTime()){
        return {kind:"unavailable"};
      }
      let parsed:unknown;
      try{parsed=JSON.parse(raw.toString("utf8"));}catch{return {kind:"unavailable"};}
      if(!parsed||typeof parsed!=="object"||Array.isArray(parsed))return {kind:"unavailable"};
      const body=parsed as {projectId?:unknown};
      if(typeof body.projectId!=="string"||!UUID.test(body.projectId)){
        return {kind:"unavailable"};
      }
      const grants=await db.query<GrantRow>(
        "SELECT p.enabled AS project_enabled,g.enabled AS grant_enabled,"+
        "p.max_mode AS project_mode,g.max_mode AS grant_mode FROM projects p "+
        "JOIN project_client_grants g ON g.project_id=p.id AND g.owner_sub=p.owner_sub "+
        "WHERE p.id=$1 AND p.device_id=$2 AND p.owner_sub=$3 AND g.client_id=$4 "+
        "FOR UPDATE OF p,g",
        [body.projectId,connection.deviceId,oauth.ownerSub,oauth.clientId]);
      const grant=grants.rows[0];
      if(!grant||!grant.project_enabled||!grant.grant_enabled||
        !["readonly","write","manufacturing"].includes(grant.project_mode)||
        !["readonly","write","manufacturing"].includes(grant.grant_mode)){
        return {kind:"unavailable"};
      }
      const request=parseBoundReadRequest(parsed,{
        authenticatedDeviceId:connection.deviceId,
        authorizedProjectId:body.projectId,
        allowedOperations:READ_OPERATIONS
      },now);
      if(!request)return {kind:"unavailable"};
      const saved=await db.query(
        "UPDATE connector_sessions SET last_sequence=$2 WHERE id=$1",
        [connection.sessionId,sequence]);
      if(saved.rowCount!==1)throw new Error("CONNECTOR_SESSION_ROW_MISSING");
      return {kind:"accepted",request,sequence};
    });
  }
}
