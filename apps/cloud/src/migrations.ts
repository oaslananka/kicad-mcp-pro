import {createHash} from "node:crypto";
import {readFile} from "node:fs/promises";
import type {Pool, PoolClient} from "pg";

export const migrationFiles = [
  "001_inventory.pgsql",
  "002_client_grants.pgsql",
  "003_better_auth.pgsql",
  "004_client_revocation.pgsql",
  "005_token_cutoff.pgsql",
  "006_oauth_issuance_fence.pgsql",
  "007_device_pairing.pgsql",
  "008_device_credentials.pgsql",
  "009_device_handshake.pgsql",
  "010_connector_sessions.pgsql",
  "011_pairing_review_budget.pgsql",
  "012_pairing_device_budget.pgsql",
  "013_owner_read_approvals.pgsql",
  "014_owner_read_approval_replay_guard.pgsql",
  "015_owner_read_webauthn_issuer.pgsql",
  "016_owner_read_passkey_registration.pgsql",
  "017_owner_read_webauthn_challenge_one_use.pgsql",
  "018_owner_read_passkey_activation.pgsql"
] as const;

type Migration = {version:number;file:string;sql:string;checksum:string};
type AppliedRow = {version:number;file_name:string;checksum:string};
export type MigrationResult = {applied:string[];pending:string[];current:number};

async function loadMigrations():Promise<Migration[]> {
  return Promise.all(migrationFiles.map(async (file,index)=>{
    const version=Number(file.slice(0,3));
    if(!Number.isSafeInteger(version) || version!==index+1){
      throw new Error("Migration manifest version order is invalid");
    }
    const sql=(await readFile(new URL("../db/"+file,import.meta.url),"utf8")).replaceAll(String.fromCodePoint(13,10),String.fromCodePoint(10));
    if(!sql.trim()) throw new Error("Empty database migration in manifest");
    return {version,file,sql,checksum:createHash("sha256").update(sql).digest("hex")};
  }));
}
async function applyPending(db:PoolClient,pending:Migration[]):Promise<void>{
  if(!pending.length) return;
  const [migration,...remaining]=pending;
  await db.query(migration.sql);
  await db.query(
    "INSERT INTO schema_migrations(version,file_name,checksum) VALUES($1,$2,$3)",
    [migration.version,migration.file,migration.checksum]
  );
  await applyPending(db,remaining);
}
async function readApplied(db:PoolClient):Promise<AppliedRow[]>{
  const existing=await db.query<{present:string|null}>(
    "SELECT to_regclass('schema_migrations')::text AS present"
  );
  if(!existing.rows[0]?.present) return [];
  const rows=await db.query<AppliedRow>(
    "SELECT version,file_name,checksum FROM schema_migrations ORDER BY version"
  );
  return rows.rows;
}
function validateHistory(migrations:Migration[],applied:AppliedRow[]):void {
  for(const row of applied){
    const current=migrations.find(m=>m.version===row.version);
    if(row.file_name!==current?.file || row.checksum!==current?.checksum){
      throw new Error("Recorded migration history conflicts with reviewed migration manifest");
    }
  }
  // Prevent an operator from recording noncontiguous schema state.
  for(let index=0;index<applied.length;index++){
    if(applied[index]?.version!==index+1){
      throw new Error("Migration history contains a version gap");
    }
  }
}
function summarize(migrations:Migration[],applied:AppliedRow[]):MigrationResult {
  return {
    applied:applied.map(m=>m.file_name),
    pending:migrations.filter(m=>m.version>applied.length).map(m=>m.file),
    current:applied.length
  };
}
/**
 * Status is read-only. Apply runs all pending, reviewed migrations in one
 * transaction, holding one transaction-scoped PostgreSQL advisory lock.
 * Never log database URLs, SQL, connection strings or secret values.
 */
export async function migrateDatabase(pool:Pool,action:"status"|"apply"):Promise<MigrationResult>{
  const migrations=await loadMigrations();
  const db=await pool.connect();
  try{
    if(action==="status"){
      const applied=await readApplied(db);
      validateHistory(migrations,applied);
      return summarize(migrations,applied);
    }
    await db.query("BEGIN");
    try{
      await db.query("SELECT pg_advisory_xact_lock(48296017)");
      await db.query(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("+
        "version integer PRIMARY KEY CHECK(version>0),"+
        "file_name text NOT NULL UNIQUE,"+
        "checksum char(64) NOT NULL,"+
        "applied_at timestamptz NOT NULL DEFAULT now())"
      );
      const applied=await readApplied(db);
      validateHistory(migrations,applied);
      await applyPending(db,migrations.slice(applied.length));
      await db.query("COMMIT");
      return summarize(migrations,migrations.map(m=>({
        version:m.version,file_name:m.file,checksum:m.checksum
      })));
    }catch(error){
      await db.query("ROLLBACK");
      throw error;
    }
  }finally{
    db.release();
  }
}
