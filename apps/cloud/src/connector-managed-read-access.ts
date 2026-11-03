import type {Pool} from "pg";
import type {TrustedOAuthReadIdentity} from "./connector-read-gate.js";

const UUID=/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

/**
 * Additional owner-managed Connector switch. OFF unless an authenticated
 * owner explicitly enables an enrolled, read-only project. Not a replacement
 * for the current OAuth project/client grant or signed device session checks.
 * Callers must authenticate the owner before calling setEnabled().
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
      "ON CONFLICT(project_id) DO UPDATE SET enabled=excluded.enabled,updated_at=now()",
      [ownerSub,deviceId,projectId,enabled]
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

  /** Deny if disabled, revoked, foreign-owned, or not a read-only project. */
  async isEnabled(oauth:TrustedOAuthReadIdentity,deviceId:string,projectId:string,
    operation:"project_summary"):Promise<boolean>{
    if(operation!=="project_summary"||!oauth||!oauth.ownerSub||
      !UUID.test(deviceId)||!UUID.test(projectId))return false;
    const result=await this.pool.query(
      "SELECT 1 FROM connector_managed_read_access m "+
      "JOIN projects p ON p.id=m.project_id "+
      "JOIN devices d ON d.id=p.device_id AND d.owner_sub=p.owner_sub "+
      "JOIN device_credentials c ON c.device_id=d.id AND c.owner_sub=d.owner_sub "+
      "WHERE p.id=$1 AND p.device_id=$2 AND p.owner_sub=$3 "+
      "AND m.enabled=true AND p.enabled=true AND d.enabled=true AND c.revoked_at IS NULL "+
      "AND p.max_mode='readonly' LIMIT 1",
      [projectId,deviceId,oauth.ownerSub]
    );
    return result.rowCount===1;
  }
}
