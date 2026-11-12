import type {Pool} from "pg";
import type {TrustedOAuthReadIdentity} from "./connector-read-gate.js";
import type {ReadOperation} from "./connector-protocol.js";

const UUID=/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const NATIVE_OPERATIONS=[
  "run_drc","project_worker_inspection","project_board_counts","project_schematic_counts"
] as const;
type ManagedNativeOperation=typeof NATIVE_OPERATIONS[number];

function validNativeOperation(operation:unknown):operation is ManagedNativeOperation {
  return NATIVE_OPERATIONS.some(candidate=>candidate===operation);
}

/**
 * Additional owner-managed Connector switch. OFF unless an authenticated
 * owner explicitly enables an enrolled, read-only project. Not a replacement
 * for current OAuth project/client grants or signed device session checks.
 * Native operations require distinct, explicit opt-in and are never inherited
 * from the existing project-summary switch.
 * Callers must authenticate the owner before mutating these grants.
 */
export class PgManagedReadAccess {
  constructor(private readonly pool:Pool){}

  async setEnabled(ownerSub:string,deviceId:string,projectId:string,enabled:boolean):Promise<boolean>{
    if(!ownerSub||ownerSub.length>256||!UUID.test(deviceId)||!UUID.test(projectId)||
       typeof enabled!=="boolean")return false;
    const result=await this.pool.query(
      "INSERT INTO connector_managed_read_access(project_id,enabled) "+
      "SELECT p.id,$4 FROM projects p JOIN devices d ON d.id=p.device_id "+
      "AND d.owner_sub=p.owner_sub WHERE p.owner_sub=$1 AND p.device_id=$2 "+
      "AND p.id=$3 AND ($4=false OR (p.enabled=true AND d.enabled=true "+
      "AND p.max_mode='readonly' AND EXISTS (SELECT 1 FROM device_credentials c "+
      "WHERE c.device_id=d.id AND c.owner_sub=d.owner_sub AND c.revoked_at IS NULL))) "+
      "ON CONFLICT(project_id) DO UPDATE SET enabled=excluded.enabled,"+
      "native_operations=CASE WHEN excluded.enabled THEN "+
      "connector_managed_read_access.native_operations ELSE '{}'::text[] END,"+
      "updated_at=now()",
      [ownerSub,deviceId,projectId,enabled]
    );
    return result.rowCount===1;
  }

  async setNativeOperation(ownerSub:string,deviceId:string,projectId:string,
    operation:ManagedNativeOperation,enabled:boolean):Promise<boolean>{
    if(!ownerSub||ownerSub.length>256||!UUID.test(deviceId)||!UUID.test(projectId)||
      !validNativeOperation(operation)||typeof enabled!=="boolean")return false;
    // Only an authenticated owner may call this method. A disabled summary
    // switch or revoked device can never acquire a native permission.
    const result=await this.pool.query(
      "UPDATE connector_managed_read_access m SET native_operations=CASE "+
      "WHEN $5 THEN CASE WHEN $4=ANY(m.native_operations) THEN m.native_operations "+
      "ELSE array_append(m.native_operations,$4::text) END "+
      "ELSE array_remove(m.native_operations,$4::text) END,updated_at=now() "+
      "FROM projects p JOIN devices d ON d.id=p.device_id AND d.owner_sub=p.owner_sub "+
      "WHERE m.project_id=p.id AND p.owner_sub=$1 AND p.device_id=$2 AND p.id=$3 "+
      "AND p.max_mode='readonly' AND (NOT $5 OR "+
      "(m.enabled=true AND p.enabled=true AND d.enabled=true AND "+
      "EXISTS (SELECT 1 FROM device_credentials c WHERE c.device_id=d.id "+
      "AND c.owner_sub=d.owner_sub AND c.revoked_at IS NULL))) "+
      "RETURNING m.project_id",
      [ownerSub,deviceId,projectId,operation,enabled]
    );
    return result.rowCount===1;
  }

  async enabledProjectIds(ownerSub:string):Promise<string[]>{
    if(!ownerSub||ownerSub.length>256)return [];
    const result=await this.pool.query<{project_id:string}>(
      "SELECT m.project_id FROM connector_managed_read_access m "+
      "JOIN projects p ON p.id=m.project_id "+
      "JOIN devices d ON d.id=p.device_id AND d.owner_sub=p.owner_sub "+
      "JOIN device_credentials c ON c.device_id=d.id AND c.owner_sub=d.owner_sub "+
      "WHERE p.owner_sub=$1 AND m.enabled=true AND p.enabled=true "+
      "AND d.enabled=true AND c.revoked_at IS NULL AND p.max_mode='readonly'",
      [ownerSub]
    );
    return result.rows.map(row=>row.project_id);
  }

  /** Deny if absent, wrong operation, disabled, revoked or foreign-owned. */
  async isEnabled(oauth:TrustedOAuthReadIdentity,deviceId:string,projectId:string,
    operation:ReadOperation):Promise<boolean>{
    if((operation!=="project_summary"&&!validNativeOperation(operation))||
      !oauth||!oauth.ownerSub||!UUID.test(deviceId)||!UUID.test(projectId))return false;
    const result=await this.pool.query(
      "SELECT 1 FROM connector_managed_read_access m "+
      "JOIN projects p ON p.id=m.project_id "+
      "JOIN devices d ON d.id=p.device_id AND d.owner_sub=p.owner_sub "+
      "JOIN device_credentials c ON c.device_id=d.id AND c.owner_sub=d.owner_sub "+
      "WHERE p.id=$1 AND p.device_id=$2 AND p.owner_sub=$3 "+
      "AND m.enabled=true AND p.enabled=true AND d.enabled=true AND c.revoked_at IS NULL "+
      "AND p.max_mode='readonly' "+
      "AND ($4='project_summary' OR $4=ANY(m.native_operations)) LIMIT 1",
      [projectId,deviceId,oauth.ownerSub,operation]
    );
    return result.rowCount===1;
  }
}
