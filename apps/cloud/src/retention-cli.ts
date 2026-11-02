import pg from "pg";
import {pruneExpiredMetadata} from "./retention.js";

const arg=process.argv.slice(2);
if(arg.length!==1||!["--dry-run","--apply"].includes(arg[0])){
  process.stderr.write("Usage: npm run db:prune -- --dry-run | --apply\n");
  process.exitCode=2;
}else if(!process.env.DATABASE_URL){
  process.stderr.write("DATABASE_URL must be supplied via authorized secrets management\n");
  process.exitCode=2;
}else{
  const pool=new pg.Pool({
    connectionString:process.env.DATABASE_URL,max:1,connectionTimeoutMillis:3000
  });
  try{
    const report=await pruneExpiredMetadata(pool,arg[0]==="--apply"?"apply":"dry-run");
    process.stdout.write(JSON.stringify(report)+"\n");
  }catch{
    process.stderr.write("Metadata retention operation failed; no connection details were logged\n");
    process.exitCode=1;
  }finally{await pool.end();}
}
