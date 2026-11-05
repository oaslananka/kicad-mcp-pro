import type {Pool,PoolClient} from "pg";
import {z} from "zod";

const UUID=z.uuid();

/**
 * Offline-only durable atomic replay reservation; NOT authorization to edit.
 * The caller must verify the trusted signer, owner/client/project grant, OAuth
 * scope and authenticated session before this operation. When called inside an
 * existing transaction, that caller can retain its revoke/grant locks through
 * the one-use reservation. Never expose this helper as an HTTP/MCP route.
 */
export async function reserveWriteProofOnce(
  db:Pool|PoolClient,sessionId:string,requestId:string,deadlineUnixMs:number
):Promise<boolean>{
  if(typeof sessionId!=="string"||typeof requestId!=="string"||
    !UUID.safeParse(sessionId).success||!UUID.safeParse(requestId).success||
    !Number.isSafeInteger(deadlineUnixMs)||deadlineUnixMs<=0)return false;
  try{
    const result=await db.query<{request_id:string}>(
      "INSERT INTO connector_write_proof_reservations "+
      "(session_id,request_id,expires_at) "+
      "SELECT $1::uuid,$2::uuid,to_timestamp($3::double precision / 1000) "+
      "WHERE to_timestamp($3::double precision / 1000)>clock_timestamp() "+
      "AND to_timestamp($3::double precision / 1000)<=clock_timestamp()+interval '10 seconds' "+
      "ON CONFLICT (request_id) DO NOTHING RETURNING request_id",
      [sessionId,requestId,deadlineUnixMs]
    );
    return result.rows.length===1;
  }catch{
    // Invalid/missing migration, DB outage or unique-key conflict fail closed.
    return false;
  }
}

/**
 * Offline-only, standalone reservation for callers that have already
 * independently verified policy. Prefer holding live policy locks in the
 * same transaction via PgConnectorWritePreflight.reserveAuthorizedWrite.
 */
export class PgWriteProofReservations{
  constructor(private readonly pool:Pool){}

  async reserveOnce(sessionId:string,requestId:string,deadlineUnixMs:number):Promise<boolean>{
    return reserveWriteProofOnce(this.pool,sessionId,requestId,deadlineUnixMs);
  }
}
