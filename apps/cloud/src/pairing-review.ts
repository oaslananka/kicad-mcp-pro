import {createHmac} from "node:crypto";
import type {Pool} from "pg";
import {PgPairingChallenges,type BrowserReview} from "./pairing-store.js";

/** Domain-separated shared pairing code key for browser and device APIs. */
export function pairingServerKey(authSecret:string):Buffer{
  if(typeof authSecret!=="string"||authSecret.length<32)
    throw new Error("PAIRING_REVIEW_SECRET_TOO_SHORT");
  return createHmac("sha256",authSecret)
    .update("kicad-cloud-pairing-user-code-v1").digest();
}

export type BrowserPairingReview=BrowserReview|"throttled";
export type PairingReviewPort=Pick<PgPairingReview,"review">;

/**
 * Per-owner, globally serialized review budget across Cloud workers.
 * Check is charged even for missing IDs or incorrect codes to avoid
 * challenge enumeration and cross-challenge brute force.
 */
export class PgPairingReview {
  private readonly store:PgPairingChallenges;
  constructor(private readonly pool:Pool,authSecret:string){
    this.store=new PgPairingChallenges(pool,pairingServerKey(authSecret));
  }
  async review(id:string,owner:string,code:string,decision:"approve"|"deny"):
    Promise<BrowserPairingReview>{
    if(!owner||owner.length>256)return "unavailable";
    const consumed=await this.pool.query<{attempts:number}>(
      "INSERT INTO pairing_review_budget(owner_sub,window_started_at,attempts) "+
      "VALUES($1,statement_timestamp(),1) ON CONFLICT(owner_sub) DO UPDATE SET "+
      "attempts=CASE WHEN pairing_review_budget.window_started_at <= "+
      "statement_timestamp()-interval '5 minutes' THEN 1 "+
      "ELSE LEAST(pairing_review_budget.attempts+1,11) END, "+
      "window_started_at=CASE WHEN pairing_review_budget.window_started_at <= "+
      "statement_timestamp()-interval '5 minutes' THEN statement_timestamp() "+
      "ELSE pairing_review_budget.window_started_at END RETURNING attempts",[owner]);
    if(consumed.rows[0]?.attempts===undefined||
      consumed.rows[0].attempts>10)return "throttled";
    return this.store.review(id,owner,code,decision);
  }
}
