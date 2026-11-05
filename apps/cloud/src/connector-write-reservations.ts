import type {Pool} from "pg";
import {z} from "zod";

const UUID=z.uuid();

/**
 * Offline-only, durable atomic replay reservation for a separately verified
 * signed Connector write proposal. This method does NOT authorize an edit:
 * callers must independently verify the trusted Ed25519 signer, owner/client/
 * project OAuth grant and current device session before reservation.
 *
 * The PostgreSQL unique request_id constraint serializes across workers.
 * Server-side clock checks reject expired or unbounded deadlines.
 * DB errors, a missing migration or conflicts all fail closed.
 * Do not expose this method as an HTTP, MCP or Connector endpoint.
 */
export class PgWriteProofReservations{
  constructor(private readonly pool:Pool){}

  async reserveOnce(sessionId:string,requestId:string,deadlineUnixMs:number):Promise<boolean>{
    if(typeof sessionId!=="string"||typeof requestId!=="string"||
      !UUID.safeParse(sessionId).success||!UUID.safeParse(requestId).success||
      !Number.isSafeInteger(deadlineUnixMs)||deadlineUnixMs<=0)return false;
    try{
      const result=await this.pool.query<{request_id:string}>(
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
      return false;
    }
  }
}
