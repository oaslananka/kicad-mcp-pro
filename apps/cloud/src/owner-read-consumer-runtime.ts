import {Pool} from "pg";
import type {OwnerReadConsentPort} from "./connector-ws.js";
import {PgOwnerReadApprovalLedger} from "./owner-read-approval-ledger.js";

export type OwnerConsentRuntime=Readonly<{
  consent:OwnerReadConsentPort;
  close:()=>Promise<void>;
}>;

/**
 * Separate, least-privileged Cloud receipt consumer. No insert capability,
 * human authentication, passkey activation or approval issuer exists here.
 * Deliberately opt-in: enabling WebSocket transport alone never enables reads.
 */
export async function openOwnerConsentRuntime(
  env:NodeJS.ProcessEnv,cloudOrigin:string,wsEnabled:boolean,
  applicationPool:Pool|null
):Promise<OwnerConsentRuntime|null>{
  const flag=env.OWNER_READ_CONSUMER_ENABLED;
  if(flag===undefined||flag==="false")return null;
  if(flag!=="true")throw Error("Invalid owner-consent consumer setting");
  if(!wsEnabled||!applicationPool||!cloudOrigin.startsWith("https://"))
    throw Error("Owner-consent consumer requires HTTPS WebSocket transport");
  const connection=env.OWNER_READ_CONSUMER_DATABASE_URL;
  if(!connection)throw Error("Missing independent owner-consent database login");
  const consumer=new Pool({
    connectionString:connection,max:4,connectionTimeoutMillis:3_000
  });
  try{
    // The application's DB session must not also be the receipt consumer.
    // Check the physical PostgreSQL principal, not URL string equivalence.
    const app=await applicationPool.query<{
      principal:string;database:string;receipt_oid:string|null
    }>("SELECT session_user AS principal,current_database() AS database,"+
      "to_regclass('owner_read_approvals')::oid::text AS receipt_oid");
    const reader=await consumer.query<{
      principal:string;database:string;receipt_oid:string|null;allowed:boolean
    }>(
      "SELECT session_user AS principal,current_database() AS database,"+
      "to_regclass('owner_read_approvals')::oid::text AS receipt_oid,"+
      "has_table_privilege(current_user,'owner_read_approvals','SELECT')"+
      " AND has_column_privilege(current_user,'owner_read_approvals','consumed_at','UPDATE')"+
      " AND NOT has_table_privilege(current_user,'owner_read_approvals','UPDATE')"+
      " AND NOT has_table_privilege(current_user,'owner_read_approvals','INSERT')"+
      " AND NOT has_table_privilege(current_user,'owner_read_approvals','DELETE')"+
      " AND NOT has_table_privilege(current_user,'owner_read_approvals','TRUNCATE')"+
      " AND NOT has_column_privilege(current_user,'owner_read_approvals','owner_sub','UPDATE')"+
      " AND NOT has_column_privilege(current_user,'owner_read_approvals','request_id','UPDATE')"+
      " AND NOT has_column_privilege(current_user,'owner_read_approvals','client_id','UPDATE')"+
      " AND NOT has_column_privilege(current_user,'owner_read_approvals','device_id','UPDATE')"+
      " AND NOT has_column_privilege(current_user,'owner_read_approvals','project_id','UPDATE')"+
      " AND NOT has_column_privilege(current_user,'owner_read_approvals','cloud_origin','UPDATE')"+
      " AND NOT has_column_privilege(current_user,'owner_read_approvals','operation','UPDATE')"+
      " AND NOT has_column_privilege(current_user,'owner_read_approvals','expires_at','UPDATE')"+
      " AND NOT has_column_privilege(current_user,'owner_read_approvals','issued_at','UPDATE')"+
      " AS allowed"
    );
    const appIdentity=app.rows[0],consumerIdentity=reader.rows[0];
    if(!appIdentity?.principal||!appIdentity.receipt_oid||
       !consumerIdentity?.allowed||!consumerIdentity.receipt_oid||
       appIdentity.principal===consumerIdentity.principal||
       appIdentity.database!==consumerIdentity.database||
       appIdentity.receipt_oid!==consumerIdentity.receipt_oid)
      throw Error("Owner-consent consumer role isolation failed");
    return {
      consent:new PgOwnerReadApprovalLedger(consumer),
      close:async()=>{await consumer.end();}
    };
  }catch{
    await consumer.end();
    // Never echo database credentials, server details or connection strings.
    throw Error("Owner-consent consumer startup denied");
  }
}
