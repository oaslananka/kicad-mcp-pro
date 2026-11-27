import {createHmac} from "node:crypto";
import type {Pool} from "pg";

/** Shared, atomic source/key budgets. No raw IP or pairing secret is stored. */
export class PgPairingBudget {
  private readonly key:Buffer;
  constructor(private readonly pool:Pool,authSecret:string){
    this.key=createHmac("sha256",authSecret)
      .update("kicad-cloud-pairing-throttle-v1").digest();
  }
  private digest(domain:string,value:string):string{
    return createHmac("sha256",this.key).update(domain).update("\0").update(value).digest("hex");
  }
  async take(domain:string,value:string,limit:number):Promise<boolean>{
    const key=this.digest(domain,value);
    const count=await this.pool.query<{attempts:number}>(
      "INSERT INTO pairing_device_budget(budget_key,window_started_at,attempts) "+
      "VALUES($1,statement_timestamp(),1) ON CONFLICT(budget_key) DO UPDATE SET "+
      "attempts=CASE WHEN pairing_device_budget.window_started_at <= "+
      "statement_timestamp()-interval '15 minutes' THEN 1 "+
      "ELSE LEAST(pairing_device_budget.attempts+1,41) END, "+
      "window_started_at=CASE WHEN pairing_device_budget.window_started_at <= "+
      "statement_timestamp()-interval '15 minutes' THEN statement_timestamp() "+
      "ELSE pairing_device_budget.window_started_at END RETURNING attempts",[key]);
    return (count.rows[0]?.attempts??42)<=limit;
  }
}
