import pg from "pg";

export interface Device {
  id: string;
  alias: string;
  enabled: boolean;
  lastSeenAt: string | null;
  connected: false;
}
export interface Project {
  id: string;
  deviceId: string;
  alias: string;
  enabled: boolean;
  maxMode: "readonly" | "write" | "manufacturing";
  available: false;
  reason: "remote_connector_not_implemented";
}
export interface Inventory {
  isAccessTokenAllowed(ownerSub:string,clientId:string,issuedAt:number):Promise<boolean>;
  listDevices(ownerSub: string, clientId: string): Promise<Device[]>;
  listProjects(ownerSub: string, clientId: string): Promise<Project[]>;
  getProject(ownerSub: string, clientId: string, projectId: string): Promise<Project | null>;
}

type DeviceRow = {id: string; alias: string; enabled: boolean; last_seen_at: Date | null};
type ProjectRow = {id: string; device_id: string; alias: string; enabled: boolean; max_mode: Project["maxMode"]};

export class PgInventory implements Inventory {
  protected readonly pool: pg.Pool;
  constructor(connectionString: string) {
    this.pool = new pg.Pool({ connectionString, max: 5, connectionTimeoutMillis: 3000, idleTimeoutMillis: 30000 });
  }
  async isAccessTokenAllowed(ownerSub:string,clientId:string,issuedAt:number):Promise<boolean> {
    if(!Number.isSafeInteger(issuedAt) || issuedAt<1 || !ownerSub || !clientId) return false;
    const result=await this.pool.query(
      "SELECT NOT EXISTS (SELECT 1 FROM client_token_cutoffs WHERE owner_sub=$1 AND client_id=$2 AND revoked_at>=to_timestamp($3)) AS allowed",
      [ownerSub,clientId,issuedAt]
    );
    return result.rows[0]?.allowed===true;
  }
  async listDevices(ownerSub: string, clientId: string): Promise<Device[]> {
    const result = await this.pool.query<DeviceRow>(
      "SELECT DISTINCT d.id,d.alias,d.enabled,d.last_seen_at FROM devices d JOIN projects p ON p.device_id=d.id AND p.owner_sub=d.owner_sub JOIN project_client_grants g ON g.project_id=p.id AND g.owner_sub=p.owner_sub WHERE d.owner_sub=$1 AND g.client_id=$2 AND g.enabled=true AND p.enabled=true AND d.enabled=true ORDER BY d.alias,d.id LIMIT 100",
      [ownerSub,clientId]
    );
    return result.rows.map(d => ({
      id: d.id, alias: d.alias, enabled: d.enabled,
      lastSeenAt: d.last_seen_at?.toISOString() ?? null,
      connected: false
    }));
  }
  async listProjects(ownerSub: string, clientId: string): Promise<Project[]> {
    const result = await this.pool.query<ProjectRow>(
      "SELECT p.id,p.device_id,p.alias,p.enabled,p.max_mode FROM projects p JOIN devices d ON d.id=p.device_id AND d.owner_sub=p.owner_sub JOIN project_client_grants g ON g.project_id=p.id AND g.owner_sub=p.owner_sub WHERE p.owner_sub=$1 AND g.client_id=$2 AND g.enabled=true AND p.enabled=true AND d.enabled=true ORDER BY p.alias,p.id LIMIT 100",
      [ownerSub,clientId]
    );
    return result.rows.map(toProject);
  }
  async getProject(ownerSub: string, clientId: string, projectId: string): Promise<Project | null> {
    const result = await this.pool.query<ProjectRow>(
      "SELECT p.id,p.device_id,p.alias,p.enabled,p.max_mode FROM projects p JOIN devices d ON d.id=p.device_id AND d.owner_sub=p.owner_sub JOIN project_client_grants g ON g.project_id=p.id AND g.owner_sub=p.owner_sub WHERE p.owner_sub=$1 AND g.client_id=$2 AND g.enabled=true AND p.id=$3 AND p.enabled=true AND d.enabled=true LIMIT 1",
      [ownerSub,clientId,projectId]
    );
    return result.rows[0] ? toProject(result.rows[0]) : null;
  }
  async close(): Promise<void> { await this.pool.end(); }
}
function toProject(p: ProjectRow): Project {
  return {
    id:p.id, deviceId:p.device_id, alias:p.alias,
    enabled:p.enabled, maxMode:p.max_mode,
    available:false, reason:"remote_connector_not_implemented"
  };
}
