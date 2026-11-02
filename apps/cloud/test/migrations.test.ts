import assert from "node:assert/strict";
import {randomBytes} from "node:crypto";
import {test} from "node:test";
import pg from "pg";
import {migrateDatabase,migrationFiles} from "../src/migrations.js";

const connectionString=process.env.TEST_DATABASE_URL;
test("migration runner is repeatable, serialized and rejects altered history",
  {skip:!connectionString}, async()=>{
  const root=new pg.Pool({connectionString});
  const schema="migration_"+randomBytes(7).toString("hex");
  let pool:pg.Pool|undefined;
  try{
    await root.query('CREATE SCHEMA "'+schema+'"');
    const scopedUrl=new URL(connectionString!);
    scopedUrl.searchParams.set("options","-c search_path="+schema);
    pool=new pg.Pool({connectionString:scopedUrl.toString(),max:3});
    const initial=await migrateDatabase(pool,"status");
    assert.equal(initial.current,0);
    assert.deepEqual(initial.pending,[...migrationFiles]);
    const before=await pool.query("SELECT to_regclass('schema_migrations') IS NOT NULL AS exists");
    assert.equal(before.rows[0]?.exists,false);
    // Two competing workers must serialize their transactional DDL.
    const [first,second]=await Promise.all([
      migrateDatabase(pool,"apply"),
      migrateDatabase(pool,"apply")
    ]);
    assert.equal(first.current,migrationFiles.length);
    assert.equal(second.current,migrationFiles.length);
    assert.deepEqual(first.pending,[]);
    assert.deepEqual(second.pending,[]);
    const latest=await migrateDatabase(pool,"status");
    assert.deepEqual(latest.applied,[...migrationFiles]);
    assert.deepEqual(latest.pending,[]);
    const appliedRows=await pool.query("SELECT version FROM schema_migrations ORDER BY version");
    assert.deepEqual(appliedRows.rows.map(row=>row.version),[1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18]);
    assert.equal((await pool.query("SELECT to_regclass($1) IS NOT NULL AS exists",['"oauthRefreshToken"'])).rows[0]?.exists,true);
    await pool.query("UPDATE schema_migrations SET checksum=repeat('0',64) WHERE version=5");
    await assert.rejects(migrateDatabase(pool,"status"),/history conflicts/);
    await assert.rejects(migrateDatabase(pool,"apply"),/history conflicts/);
    assert.equal((await pool.query("SELECT count(*)::integer AS count FROM schema_migrations")).rows[0]?.count,18);
  }finally{
    await pool?.end();
    await root.query('DROP SCHEMA IF EXISTS "'+schema+'" CASCADE');
    await root.end();
  }
});
test("migrations require an explicit action",async()=>{
  const source=await import("../src/migrations.js");
  assert.equal(source.migrationFiles.length,18);
});
