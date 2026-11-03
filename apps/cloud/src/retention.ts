import type {Pool,PoolClient} from "pg";

const BATCH_SIZE=100;

/**
 * Security-sensitive identity data is held for an explicit 30-day grace
 * period after its hard expiration; activity budgets for 24 hours after
 * their window began (well beyond their 5- or 15-minute enforcement).
 *
 * This is deliberately one bounded, opt-in invocation; no cron daemon.
 */
export type RetentionTable=
  "connector_sessions"|"device_handshake_challenges"|"pairing_challenges"|
  "pairing_review_budget"|"pairing_device_budget";
const ORDER:readonly RetentionTable[]=[
  "connector_sessions",
  "device_handshake_challenges",
  "pairing_challenges",
  "pairing_review_budget",
  "pairing_device_budget"
];
const PAIRING_GRACE="30 days";
const BUDGET_GRACE="24 hours";
export type RetentionAction="dry-run"|"apply";
export type RetentionSummary={
  mode:RetentionAction;
  batchLimit:number;
  // Dry run returns at most batchLimit+1 matching records per table.
  // An exact remaining total is intentionally not computed.
  tables:Record<RetentionTable,{eligible:number;hasMore:boolean;deleted:number}>;
};

function selection(table:RetentionTable):{key:string;condition:string}{
  if(table==="connector_sessions")return {
    key:"id",
    condition:"expires_at < statement_timestamp() - interval '"+PAIRING_GRACE+"'"
  };
  if(table==="device_handshake_challenges")return {
    key:"id",
    condition:"expires_at < statement_timestamp() - interval '"+PAIRING_GRACE+"' "+
      "AND NOT EXISTS (SELECT 1 FROM connector_sessions s "+
      "WHERE s.handshake_id=device_handshake_challenges.id)"
  };
  if(table==="pairing_challenges")return {
    key:"id",
    condition:"expires_at < statement_timestamp() - interval '"+PAIRING_GRACE+"' "+
      "AND NOT EXISTS (SELECT 1 FROM device_credentials c "+
      "WHERE c.pairing_challenge_id=pairing_challenges.id)"
  };
  if(table==="pairing_review_budget")return {
    key:"owner_sub",
    condition:"window_started_at < statement_timestamp() - interval '"+BUDGET_GRACE+"'"
  };
  return {
    key:"budget_key",
    condition:"window_started_at < statement_timestamp() - interval '"+BUDGET_GRACE+"'"
  };
}

async function preview(db:PoolClient,table:RetentionTable):Promise<{eligible:number;hasMore:boolean;deleted:number}>{
  const {condition}=selection(table);
  const {rows}=await db.query<{eligible:string}>(
    "SELECT count(*)::text AS eligible FROM (SELECT 1 FROM "+table+
    " WHERE "+condition+" LIMIT $1) bounded",[BATCH_SIZE+1]
  );
  const count=Number(rows[0]?.eligible??0);
  return {eligible:Math.min(BATCH_SIZE,count),hasMore:count>BATCH_SIZE,deleted:0};
}
async function erase(db:PoolClient,table:RetentionTable):Promise<number>{
  const {key,condition}=selection(table);
  // SKIP LOCKED leaves rows currently being reviewed/updated untouched.
  // No CASCADE: credential-linked pairings and session-linked handshakes stay.
  const result=await db.query(
    "WITH victims AS (SELECT "+key+" FROM "+table+" WHERE "+condition+
    " ORDER BY "+key+" FOR UPDATE SKIP LOCKED LIMIT $1) "+
    "DELETE FROM "+table+" t USING victims "+
    "WHERE t."+key+"=victims."+key,[BATCH_SIZE]);
  return result.rowCount??0;
}
export async function pruneExpiredMetadata(
  pool:Pool,action:RetentionAction="dry-run"
):Promise<RetentionSummary>{
  if(action!=="dry-run"&&action!=="apply")throw new Error("INVALID_RETENTION_ACTION");
  const db=await pool.connect();
  try{
    await db.query("BEGIN");
    try{
      // Fail closed on heavyweight table locks and unbounded query work.
      if(action==="dry-run")await db.query("SET TRANSACTION READ ONLY");
      await db.query("SET LOCAL lock_timeout = '2s'");
      await db.query("SET LOCAL statement_timeout = '10s'");
      const tables={} as RetentionSummary["tables"];
      for(const table of ORDER){
        const before=await preview(db,table);
        const deleted=action==="apply"?await erase(db,table):0;
        tables[table]={...before,deleted};
      }
      await db.query("COMMIT");
      return {mode:action,batchLimit:BATCH_SIZE,tables};
    }catch(error){
      try{await db.query("ROLLBACK");}catch{/* keep original error */}
      throw error;
    }
  }finally{db.release();}
}
