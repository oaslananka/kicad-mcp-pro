import type {Pool} from "pg";
import type {OwnerReadConsentPort} from "./connector-ws.js";

const UUID=/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

/**
 * Atomic receipt consumer, NOT owner authentication or a receipt issuer.
 *
 * Approval rows may be created ONLY by a separately authenticated,
 * independently user-verifying authority with a restricted DB role.
 * This module exposes NO method to insert or approve a receipt. Its consume
 * statement refuses a database identity with broad table-write permissions
 * or mutable receipt identity fields (including owner/superuser). Production
 * must use a distinct read-only-plus-consumed_at-update runtime DB role.
 * The Cloud production composition does not instantiate/wire this consumer.
 *
 * PostgreSQL serializes concurrent consumes on request_id; all identity,
 * operation and expiry bindings must match BEFORE the same statement marks
 * the record consumed. Never select-then-update or tolerate missing rows.
 */
export class PgOwnerReadApprovalLedger implements OwnerReadConsentPort{
  constructor(private readonly db:Pool){}
  async consume(scope:Parameters<OwnerReadConsentPort["consume"]>[0]):Promise<boolean>{
    if(!scope||!scope.oauth||
      typeof scope.oauth.ownerSub!=="string"||!scope.oauth.ownerSub||
      scope.oauth.ownerSub.length>256||
      typeof scope.oauth.clientId!=="string"||!scope.oauth.clientId||
      scope.oauth.clientId.length>1024||
      typeof scope.origin!=="string"||!scope.origin.startsWith("https://")||
      scope.origin.length>256||
      !UUID.test(scope.requestId)||!UUID.test(scope.deviceId)||!UUID.test(scope.projectId)||
      scope.operation!=="project_summary"||
      !Number.isSafeInteger(scope.expiresAtUnixMs)||scope.expiresAtUnixMs<=0)return false;
    // The PostgreSQL clock, not a locally controlled process clock,
    // determines expiration and ensures no approval can be reused.
    const result=await this.db.query(
      "UPDATE owner_read_approvals SET consumed_at=clock_timestamp() "+
      "WHERE request_id=$1 AND owner_sub=$2 AND client_id=$3 "+
      "AND device_id=$4 AND project_id=$5 AND cloud_origin=$6 "+
      "AND operation=$7 AND expires_at=to_timestamp($8::double precision/1000) "+
      "AND consumed_at IS NULL AND clock_timestamp()<expires_at "+
      // A consumer permitted to INSERT, DELETE or rewrite receipt identity
      // fields could mint/falsify its own approval. Never trust that role.
      // Also denies superusers and table owners (both have these privileges).
      "AND NOT has_table_privilege(current_user,'owner_read_approvals','INSERT') "+
      "AND NOT has_table_privilege(current_user,'owner_read_approvals','DELETE') "+
      "AND NOT has_table_privilege(current_user,'owner_read_approvals','TRUNCATE') "+
      "AND NOT has_column_privilege(current_user,'owner_read_approvals','request_id','UPDATE') "+
      "AND NOT has_column_privilege(current_user,'owner_read_approvals','owner_sub','UPDATE') "+
      "AND NOT has_column_privilege(current_user,'owner_read_approvals','client_id','UPDATE') "+
      "AND NOT has_column_privilege(current_user,'owner_read_approvals','device_id','UPDATE') "+
      "AND NOT has_column_privilege(current_user,'owner_read_approvals','project_id','UPDATE') "+
      "AND NOT has_column_privilege(current_user,'owner_read_approvals','cloud_origin','UPDATE') "+
      "AND NOT has_column_privilege(current_user,'owner_read_approvals','operation','UPDATE') "+
      "AND NOT has_column_privilege(current_user,'owner_read_approvals','expires_at','UPDATE') "+
      "AND NOT has_column_privilege(current_user,'owner_read_approvals','issued_at','UPDATE') "+
      "RETURNING request_id",
      [scope.requestId,scope.oauth.ownerSub,scope.oauth.clientId,
       scope.deviceId,scope.projectId,scope.origin,scope.operation,scope.expiresAtUnixMs]);
    return result.rowCount===1;
  }
}
