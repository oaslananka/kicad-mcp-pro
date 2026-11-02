import pg from "pg";
import {migrateDatabase} from "./migrations.js";

const args=process.argv.slice(2);
if(args.length!==1 || !["--status","--apply"].includes(args[0])){
  process.stderr.write("Usage: npm run db:migrate -- --status | --apply\n");
  process.exitCode=2;
}else if(!process.env.DATABASE_URL){
  process.stderr.write("DATABASE_URL is required; inject it via a controlled Doppler configuration\n");
  process.exitCode=2;
}else{
  const pool=new pg.Pool({connectionString:process.env.DATABASE_URL,max:1,connectionTimeoutMillis:3000});
  try{
    const action=args[0]==="--apply"?"apply":"status";
    const result=await migrateDatabase(pool,action);
    process.stdout.write(JSON.stringify(result)+"\n");
  }catch{
    // Do not include potentially sensitive database connection error details.
    process.stderr.write("Migration validation or application failed; no connection values were logged\n");
    process.exitCode=1;
  }finally{
    await pool.end();
  }
}
