import type { PoolClient } from "pg";
import { PgInventory } from "./store.js";

export type AccessMode = "readonly" | "write" | "manufacturing";
export type GrantInput = {
  clientId: string;
  enabled: boolean;
  maxMode: AccessMode;
};

export interface GrantManagement {
  setGrant(ownerSub: string, actorClientId: string, projectId: string, grant: GrantInput): Promise<boolean>;
  revokeClient(ownerSub: string, clientId: string): Promise<number>;
  setBrowserGrant?(ownerSub:string,projectId:string,clientId:string,enabled:boolean):Promise<boolean>;
}

export class PgGrantManagement extends PgInventory implements GrantManagement {
  constructor(connectionString:string, private readonly builtInTokenStore=false) {
    super(connectionString);
  }
  async revokeClient(ownerSub: string, clientId: string): Promise<number> {
    const db = await this.pool.connect();
    try {
      await db.query("BEGIN");
      if (this.builtInTokenStore) {
        // Serialize with the issuance/replay triggers, including across
        // independent Cloud instances that share this PostgreSQL database.
        await db.query(
          "SELECT pg_advisory_xact_lock(hashtextextended($1 || chr(31) || $2, 48296018))",
          [ownerSub,clientId]
        );
      }
      await db.query(
        "INSERT INTO client_token_cutoffs(owner_sub,client_id,revoked_at) VALUES($1,$2,now()) ON CONFLICT(owner_sub,client_id) DO UPDATE SET revoked_at=excluded.revoked_at",
        [ownerSub,clientId]
      );
      if (this.builtInTokenStore) {
        // Clear rotated refresh-token replay caches as well as active tokens.
        await db.query(
          'UPDATE "oauthRefreshToken" SET "revoked"=COALESCE("revoked",now()), "rotationReplayResponse"=NULL, "rotationReplayExpiresAt"=NULL WHERE "userId"=$1 AND "clientId"=$2',
          [ownerSub,clientId]
        );
        await db.query(
          'UPDATE "oauthAccessToken" SET "revoked"=COALESCE("revoked",now()) WHERE "userId"=$1 AND "clientId"=$2',
          [ownerSub,clientId]
        );
      }
      const result = await db.query<{project_id:string}>(
        "UPDATE project_client_grants SET enabled=false WHERE owner_sub=$1 AND client_id=$2 AND enabled=true RETURNING project_id",
        [ownerSub,clientId]
      );
      if (result.rows.length) {
        await db.query(
          "INSERT INTO client_grant_audit(owner_sub,actor_client_id,project_id,operation) SELECT $1,$2,id,'client.revoke' FROM unnest($3::uuid[]) AS id",
          [ownerSub,clientId,result.rows.map(row=>row.project_id)]
        );
      }
      await db.query("COMMIT");
      return result.rowCount ?? 0;
    } catch(e) {
      await db.query("ROLLBACK");
      throw e;
    } finally {
      db.release();
    }
  }
  /**
   * Owner's browser-only consent grant. Must not re-enable a client whose
   * OAuth consent predates the revocation cutoff; serialize with revokeClient.
   * Never accepts a write/manufacturing mode or local project path.
   */
  async setBrowserGrant(owner:string,projectId:string,clientId:string,enabled:boolean):Promise<boolean>{
    const uuid=/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
    if(!this.builtInTokenStore||!owner||owner.length>256||!uuid.test(projectId)||
      !clientId||clientId.length>1024||typeof enabled!=="boolean")return false;
    const db=await this.pool.connect();
    try{
      await db.query("BEGIN");
      await db.query(
        "SELECT pg_advisory_xact_lock(hashtextextended($1 || chr(31) || $2, 48296018))",
        [owner,clientId]);
      const project=await db.query(
        "SELECT p.id FROM projects p JOIN devices d ON d.id=p.device_id AND d.owner_sub=p.owner_sub "+
        "JOIN device_credentials k ON k.device_id=d.id AND k.owner_sub=d.owner_sub "+
        "WHERE p.id=$1 AND p.owner_sub=$2 AND p.max_mode='readonly' AND p.enabled=true "+
        "AND d.enabled=true AND k.revoked_at IS NULL FOR UPDATE OF p,d,k",
        [projectId,owner]);
      if(project.rowCount!==1){await db.query("ROLLBACK");return false;}
      if(enabled){
        const consent=await db.query<{created_at:Date}>(
          'SELECT c."createdAt" AS created_at FROM "oauthConsent" c '+
          'JOIN "oauthClient" o ON o."clientId"=c."clientId" '+
          'WHERE c."userId"=$1 AND c."clientId"=$2 AND c."scopes" @> $3::jsonb '+
          'AND o."disabled" IS DISTINCT FROM true ORDER BY c."createdAt" DESC LIMIT 1 '+
          'FOR SHARE OF c,o',[owner,clientId,JSON.stringify(["projects:read"])]);
        const created=consent.rows[0]?.created_at;
        if(!created){await db.query("ROLLBACK");return false;}
        const revoked=await db.query<{revoked_at:Date}>(
          "SELECT revoked_at FROM client_token_cutoffs WHERE owner_sub=$1 AND client_id=$2 FOR SHARE",
          [owner,clientId]);
        if(revoked.rows[0]&&created.getTime()<=revoked.rows[0].revoked_at.getTime()){
          await db.query("ROLLBACK");return false;
        }
      }
      await db.query(
        "INSERT INTO project_client_grants(project_id,owner_sub,client_id,enabled,max_mode) "+
        "VALUES($1,$2,$3,$4,'readonly') ON CONFLICT(project_id,client_id) DO UPDATE SET "+
        "enabled=excluded.enabled,max_mode='readonly' "+
        "WHERE project_client_grants.owner_sub=excluded.owner_sub",
        [projectId,owner,clientId,enabled]);
      await db.query(
        "INSERT INTO client_grant_audit(owner_sub,actor_client_id,project_id,operation) "+
        "VALUES($1,$2,$3,'grant.set')",[owner,"owner-browser",projectId]);
      await db.query("COMMIT");
      return true;
    }catch(error){
      try{await db.query("ROLLBACK");}catch{/* original error */}
      throw error;
    }finally{db.release();}
  }

  async setGrant(ownerSub: string, actorClientId: string, projectId: string, grant: GrantInput): Promise<boolean> {
    const db: PoolClient = await this.pool.connect();
    try {
      await db.query("BEGIN");
      // Serialize against future project mode/ownership changes, and never accept foreign owners.
      const project = await db.query<{max_mode: AccessMode}>(
        "SELECT max_mode FROM projects WHERE id=$1 AND owner_sub=$2 FOR UPDATE", [projectId, ownerSub]
      );
      if (!project.rows[0]) {
        await db.query("ROLLBACK");
        return false;
      }
      if (grant.enabled && grant.maxMode !== "readonly" && grant.maxMode !== project.rows[0].max_mode) {
        throw new Error("POLICY_EXCEEDS_PROJECT");
      }
      await db.query(
        "INSERT INTO project_client_grants(project_id,owner_sub,client_id,enabled,max_mode) VALUES($1,$2,$3,$4,$5) ON CONFLICT(project_id,client_id) DO UPDATE SET enabled=excluded.enabled,max_mode=excluded.max_mode WHERE project_client_grants.owner_sub=excluded.owner_sub",
        [projectId,ownerSub,grant.clientId,grant.enabled,grant.maxMode]
      );
      await db.query(
        "INSERT INTO client_grant_audit(owner_sub,actor_client_id,project_id,operation) VALUES($1,$2,$3,'grant.set')",
        [ownerSub,actorClientId,projectId]
      );
      await db.query("COMMIT");
      return true;
    } catch (e) {
      await db.query("ROLLBACK");
      throw e;
    } finally {
      db.release();
    }
  }
}