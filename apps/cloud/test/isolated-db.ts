import {randomBytes} from "node:crypto";
import {readFile} from "node:fs/promises";
import pg from "pg";

/**
 * Test-only PostgreSQL schema sandbox; migrations are applied to an isolated
 * schema and it is always torn down, including after assertion failures.
 * Never pass a production database URL.
 */
export async function inIsolatedDatabase<T>(
  connectionString:string,
  migrationNames:readonly string[],
  action:(db:pg.Pool)=>Promise<T>
):Promise<T>{
  const administrator=new pg.Pool({connectionString});
  const identifier="fixture_"+randomBytes(9).toString("hex");
  let fixture:pg.Pool|undefined;
  try{
    await administrator.query('CREATE SCHEMA "'+identifier+'"');
    const target=new URL(connectionString);
    target.searchParams.set("options","-c search_path="+identifier);
    fixture=new pg.Pool({connectionString:target.toString(),max:8});
    for(const migration of migrationNames){
      const sql=await readFile(new URL("../db/"+migration,import.meta.url),"utf8");
      await fixture.query(sql);
    }
    return await action(fixture);
  }finally{
    await fixture?.end();
    await administrator.query('DROP SCHEMA IF EXISTS "'+identifier+'" CASCADE');
    await administrator.end();
  }
}
