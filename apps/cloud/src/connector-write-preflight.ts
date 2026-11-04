import {createHash,timingSafeEqual} from "node:crypto";
import type {Pool} from "pg";
import type {Actor} from "./auth.js";
import type {TrustedConnectorContext} from "./connector-read-gate.js";
import {lockActiveDeviceKey,withDeviceTransaction} from "./device-db-transaction.js";

const UUID=/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const BINDING=/^[A-Za-z0-9_-]{43}$/;
const HASH=/^[0-9a-f]{64}$/;

function validIdentity(actor:Actor,connection:TrustedConnectorContext,projectId:string):boolean{
  return !!actor&&!!connection&&typeof actor.sub==="string"&&
    actor.sub.length>0&&actor.sub.length<=256&&
    typeof actor.clientId==="string"&&actor.clientId.length>0&&
    actor.clientId.length<=1024&&actor.scopes instanceof Set&&
    actor.scopes.has("projects:read")&&actor.scopes.has("projects:write")&&
    Number.isSafeInteger(actor.issuedAt)&&actor.issuedAt>0&&
    UUID.test(projectId)&&UUID.test(connection.deviceId)&&
    UUID.test(connection.sessionId)&&
    typeof connection.connectionBinding==="string"&&
    BINDING.test(connection.connectionBinding)&&
    Buffer.from(connection.connectionBinding,"base64url").toString("base64url")===
      connection.connectionBinding&&
    Buffer.from(connection.connectionBinding,"base64url").length===32;
}
function bindingMatches(binding:string,digest:string):boolean{
  if(!HASH.test(digest))return false;
  return timingSafeEqual(createHash("sha256").update(binding,"utf8").digest(),
    Buffer.from(digest,"hex"));
}

/**
 * Offline-only, deny-by-default prerequisite for owner-approved remote edits.
 *
 * The Actor MUST originate from the verified OAuth resource-server middleware,
 * and the connector context MUST originate from an authenticated server-owned
 * device socket. Callers must not construct either from tool/HTTP arguments.
 *
 * This check NEVER executes or authorizes a KiCad mutation: the result expires
 * as soon as the transaction commits. An actual local edit will require a new
 * per-command, signed and consumed authorization after this preflight, plus
 * local project/revision checks. Do not expose this as an MCP tool or route.
 */
export class PgConnectorWritePreflight{
  constructor(private readonly pool:Pool){}

  async checkCurrentPolicy(
    actor:Actor,connection:TrustedConnectorContext,projectId:string
  ):Promise<boolean>{
    if(!validIdentity(actor,connection,projectId))return false;
    return withDeviceTransaction(this.pool,async db=>{
      // Match device revocation's lock order; a disabled/revoked credential
      // never allows a write even if a stale project grant remains.
      if(!await lockActiveDeviceKey(db,actor.sub,connection.deviceId))return false;
      const session=await db.query<{
        state:string;expires_at:Date;connection_digest:string;
      }>(
        "SELECT state,expires_at,connection_digest FROM connector_sessions "+
        "WHERE id=$1 AND device_id=$2 AND owner_sub=$3 FOR UPDATE",
        [connection.sessionId,connection.deviceId,actor.sub]
      );
      const active=session.rows[0];
      if(!active||active.state!=="active"||
        !bindingMatches(connection.connectionBinding,active.connection_digest))return false;
      const clock=await db.query<{now_ms:string}>(
        "SELECT floor(extract(epoch FROM clock_timestamp())*1000)::bigint AS now_ms");
      const now=Number(clock.rows[0]?.now_ms);
      if(!Number.isSafeInteger(now)||now<=0||now>=active.expires_at.getTime()||
        actor.issuedAt*1000>now+5_000)return false;

      // Client revoke holds the cutoff lock before grant rows. Matching that
      // order prevents stale re-grants and avoids lock-order inversion.
      const cutoff=await db.query<{revoked_at:Date}>(
        "SELECT revoked_at FROM client_token_cutoffs "+
        "WHERE owner_sub=$1 AND client_id=$2 FOR SHARE",
        [actor.sub,actor.clientId]);
      const revokedAt=cutoff.rows[0]?.revoked_at;
      if(revokedAt&&actor.issuedAt*1000<=revokedAt.getTime())return false;

      const grants=await db.query<{
        project_enabled:boolean;grant_enabled:boolean;
        project_mode:string;grant_mode:string;
      }>(
        "SELECT p.enabled AS project_enabled,g.enabled AS grant_enabled,"+
        "p.max_mode AS project_mode,g.max_mode AS grant_mode "+
        "FROM projects p JOIN project_client_grants g "+
        "ON g.project_id=p.id AND g.owner_sub=p.owner_sub "+
        "WHERE p.id=$1 AND p.owner_sub=$2 AND p.device_id=$3 "+
        "AND g.client_id=$4 FOR SHARE OF p,g",
        [projectId,actor.sub,connection.deviceId,actor.clientId]
      );
      const grant=grants.rows[0];
      // Manufacturing grants are deliberately NOT a shortcut for writes.
      return !!grant&&grant.project_enabled&&grant.grant_enabled&&
        grant.project_mode==="write"&&grant.grant_mode==="write";
    });
  }
}
