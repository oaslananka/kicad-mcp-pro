import type {Pool,PoolClient} from "pg";

/**
 * All device identity operations lock the device and credential in the
 * same order. This is shared by challenge, connector session and revoke.
 */
export async function withDeviceTransaction<T>(
  pool:Pool, action:(db:PoolClient)=>Promise<T>
):Promise<T>{
  const db=await pool.connect();
  try{
    await db.query("BEGIN");
    const result=await action(db);
    await db.query("COMMIT");
    return result;
  }catch(error){
    try{await db.query("ROLLBACK");}catch{/* preserve original error */}
    throw error;
  }finally{
    db.release();
  }
}

export async function lockActiveDeviceKey(
  db:PoolClient,owner:string,deviceId:string
):Promise<string|null>{
  const result=await db.query<{public_key_der:string}>(
    "SELECT c.public_key_der FROM devices d "+
    "JOIN device_credentials c ON c.device_id=d.id AND c.owner_sub=d.owner_sub "+
    "WHERE d.id=$1 AND d.owner_sub=$2 AND d.enabled=true AND c.revoked_at IS NULL "+
    "FOR UPDATE OF d,c",[deviceId,owner]);
  return result.rows[0]?.public_key_der??null;
}
