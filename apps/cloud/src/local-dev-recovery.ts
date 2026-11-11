import type {Pool} from "pg";

/**
 * Single-process loopback sandbox recovery. Node's sockets disappear on
 * process termination, but the production SQL lease still marks them active.
 * Only the synthetic sandbox owner may be reset on startup; do not apply
 * this operation to real owners, Cloud deployments or multi-worker servers.
 */
export async function recoverLocalDevSessions(pool:Pick<Pool,"connect">):Promise<void>{
  const client=await pool.connect();
  try{
    await client.query("BEGIN");
    await client.query(
      "UPDATE connector_sessions SET state='closed' "+
      "WHERE owner_sub=$1 AND state IN ('pending','active')",
      ["local-dev-owner"]
    );
    await client.query(
      "UPDATE device_handshake_challenges SET status='revoked' "+
      "WHERE owner_sub=$1 AND status='pending'",
      ["local-dev-owner"]
    );
    await client.query("COMMIT");
  }catch(error){
    await client.query("ROLLBACK");
    throw error;
  }finally{client.release();}
}