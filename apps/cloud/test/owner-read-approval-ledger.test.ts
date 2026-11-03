import assert from "node:assert/strict";
import {randomUUID} from "node:crypto";
import {test} from "node:test";
import {Pool} from "pg";
import type {Pool as PoolType} from "pg";
import {inIsolatedDatabase} from "./isolated-db.js";
import {PgOwnerReadApprovalLedger} from "../src/owner-read-approval-ledger.js";

const url=process.env.TEST_DATABASE_URL;

/** Disposable PostgreSQL role boundary: the issuer fixture uses the schema
 * owner, while the Cloud consumer may SELECT and UPDATE consumed_at only.
 * Credentials and test roles exist exclusively in isolated PostgreSQL 17.
 */
async function withRestrictedConsumer(
  admin:PoolType,action:(consumer:PoolType)=>Promise<void>
):Promise<void>{
  // Fixed fixture-only name avoids ever constructing SQL with a JS identifier.
  // Node's test runner executes this file's top-level tests sequentially; each
  // fixture drops this role before the next starts.
  const role="cloud_approval_fixture_reader";
  const password="isolated_postgres_fixture_only";
  const schema=(await admin.query<{schema:string}>(
    "SELECT current_schema() AS schema")).rows[0]?.schema;
  if(!schema||!/^fixture_[a-f0-9]{18}$/.test(schema))throw Error("Unsafe test schema");
  await admin.query(
    "CREATE ROLE cloud_approval_fixture_reader LOGIN PASSWORD 'isolated_postgres_fixture_only'");
  let consumer:PoolType|undefined;
  try{
    // PostgreSQL's own %I identifier quoting uses the isolated current_schema.
    // The entire SQL text is static; no input is manually concatenated into it.
    await admin.query(
      "DO $plpgsql$ BEGIN EXECUTE format("+
      "'GRANT USAGE ON SCHEMA %I TO cloud_approval_fixture_reader',"+
      "current_schema()); END $plpgsql$");
    await admin.query(
      "GRANT SELECT ON owner_read_approvals TO cloud_approval_fixture_reader");
    await admin.query(
      "GRANT UPDATE(consumed_at) ON owner_read_approvals TO cloud_approval_fixture_reader");
    const target=new URL(url!);
    target.username=role;
    target.password=password;
    target.searchParams.set("options","-c search_path="+schema);
    consumer=new Pool({connectionString:target.toString(),max:16});
    const connected=await consumer.query<{who:string}>(
      "SELECT current_user AS who");
    assert.equal(connected.rows[0]?.who,role);
    await action(consumer);
  }finally{
    await consumer?.end();
    await admin.query("DROP OWNED BY cloud_approval_fixture_reader");
    await admin.query("DROP ROLE cloud_approval_fixture_reader");
  }
}
const scope=()=>({
  oauth:{ownerSub:"verified-owner",clientId:"verified-client",accessTokenIssuedAtSeconds:1760000000},
  deviceId:randomUUID(),projectId:randomUUID(),requestId:randomUUID(),
  origin:"https://trusted-owner.example",operation:"project_summary" as const,
  expiresAtUnixMs:Date.now()+20_000
});

test("trusted owner approval receipt is consumed once across competing workers",
  {skip:!url},async()=>{
  await inIsolatedDatabase(url!,["013_owner_read_approvals.pgsql","014_owner_read_approval_replay_guard.pgsql"],async db=>{
    await withRestrictedConsumer(db,async consumer=>{
    const verifier=new PgOwnerReadApprovalLedger(consumer);
    const agreed=scope();
    assert.equal(await verifier.consume(agreed),false,"missing assertion must deny");
    // Synthetic fixture only; no API/service writes trusted approvals yet.
    await db.query("INSERT INTO owner_read_approvals "+
      "(request_id,owner_sub,client_id,device_id,project_id,cloud_origin,operation,expires_at) "+
      "VALUES($1,$2,$3,$4,$5,$6,$7,to_timestamp($8::double precision/1000))",
      [agreed.requestId,agreed.oauth.ownerSub,agreed.oauth.clientId,agreed.deviceId,
       agreed.projectId,agreed.origin,agreed.operation,agreed.expiresAtUnixMs]);
    const races=await Promise.all(Array.from({length:12},()=>verifier.consume(agreed)));
    assert.equal(races.filter(Boolean).length,1);
    assert.equal(await verifier.consume(agreed),false);
    const row=await db.query("SELECT consumed_at FROM owner_read_approvals WHERE request_id=$1",
      [agreed.requestId]);
    assert.ok(row.rows[0]?.consumed_at);
    });
  });
});

test("bound scope, missing receipt, expiry and malformed caller fail closed",
  {skip:!url},async()=>{
  await inIsolatedDatabase(url!,["013_owner_read_approvals.pgsql","014_owner_read_approval_replay_guard.pgsql"],async db=>{
    await withRestrictedConsumer(db,async consumer=>{
    const verifier=new PgOwnerReadApprovalLedger(consumer);
    const agreed=scope();
    await db.query("INSERT INTO owner_read_approvals "+
      "(request_id,owner_sub,client_id,device_id,project_id,cloud_origin,operation,expires_at) "+
      "VALUES($1,$2,$3,$4,$5,$6,$7,to_timestamp($8::double precision/1000))",
      [agreed.requestId,agreed.oauth.ownerSub,agreed.oauth.clientId,agreed.deviceId,
       agreed.projectId,agreed.origin,agreed.operation,agreed.expiresAtUnixMs]);
    for(const invalid of [
      {...agreed,oauth:{...agreed.oauth,ownerSub:"other"}},
      {...agreed,oauth:{...agreed.oauth,clientId:"other"}},
      {...agreed,deviceId:randomUUID()},
      {...agreed,projectId:randomUUID()},
      {...agreed,origin:"https://other.example"},
      {...agreed,operation:"run_drc" as "project_summary"},
      {...agreed,expiresAtUnixMs:agreed.expiresAtUnixMs+1},
      {...agreed,requestId:randomUUID()},
      {...agreed,requestId:"not-a-uuid"}
    ])assert.equal(await verifier.consume(invalid),false);
    assert.equal(await verifier.consume(agreed),true,"invalid attempts cannot burn approval");
    assert.equal(await verifier.consume(agreed),false);
    const expired=scope();
    await db.query("INSERT INTO owner_read_approvals "+
      "(request_id,owner_sub,client_id,device_id,project_id,cloud_origin,operation,expires_at) "+
      "VALUES($1,$2,$3,$4,$5,$6,$7,to_timestamp($8::double precision/1000))",
      [expired.requestId,expired.oauth.ownerSub,expired.oauth.clientId,expired.deviceId,
       expired.projectId,expired.origin,expired.operation,expired.expiresAtUnixMs]);
    await db.query("UPDATE owner_read_approvals SET expires_at=clock_timestamp()-interval '1 second',"+
      "issued_at=clock_timestamp()-interval '5 seconds' WHERE request_id=$1",[expired.requestId]);
    assert.equal(await verifier.consume(expired),false,"expired DB approval denied");
    });
  });
});

test("consumer cannot issue, rewrite, delete or truncate owner decisions; owner role cannot consume",
  {skip:!url},async()=>{
  await inIsolatedDatabase(url!,["013_owner_read_approvals.pgsql","014_owner_read_approval_replay_guard.pgsql"],async db=>{
    await withRestrictedConsumer(db,async consumer=>{
      const agreed=scope();
      await db.query("INSERT INTO owner_read_approvals "+
        "(request_id,owner_sub,client_id,device_id,project_id,cloud_origin,operation,expires_at) "+
        "VALUES($1,$2,$3,$4,$5,$6,$7,to_timestamp($8::double precision/1000))",
        [agreed.requestId,agreed.oauth.ownerSub,agreed.oauth.clientId,
          agreed.deviceId,agreed.projectId,agreed.origin,agreed.operation,
          agreed.expiresAtUnixMs]);
      const forbidden=[
        ()=>consumer.query("INSERT INTO owner_read_approvals "+
          "(request_id,owner_sub,client_id,device_id,project_id,cloud_origin,operation,expires_at) "+
          "VALUES($1,$2,$3,$4,$5,$6,$7,to_timestamp($8::double precision/1000))",
          [randomUUID(),agreed.oauth.ownerSub,agreed.oauth.clientId,
            agreed.deviceId,agreed.projectId,agreed.origin,agreed.operation,
            agreed.expiresAtUnixMs]),
        ()=>consumer.query("UPDATE owner_read_approvals SET owner_sub='forged' WHERE request_id=$1",
          [agreed.requestId]),
        ()=>consumer.query("DELETE FROM owner_read_approvals WHERE request_id=$1",
          [agreed.requestId]),
        ()=>consumer.query("TRUNCATE owner_read_approvals")
      ];
      for(const attempt of forbidden){
        await assert.rejects(attempt(),(err:unknown)=>
          Boolean(err&&typeof err==="object"&&"code" in err&&err.code==="42501"));
      }
      const operator=new PgOwnerReadApprovalLedger(db);
      assert.equal(await operator.consume(agreed),false,
        "A privileged table owner must not consume or forge owner approvals");
      const reader=new PgOwnerReadApprovalLedger(consumer);
      assert.equal(await reader.consume(agreed),true,
        "Least-privileged reader may atomically burn one real fixture receipt");
      assert.equal(await reader.consume(agreed),false,
        "Duplicate consumption must fail");
      // A receipt reader is allowed to update consumed_at ONLY. Unless the
      // database blocks resetting it, the same approval can be replayed.
      await assert.rejects(
        consumer.query("UPDATE owner_read_approvals SET consumed_at=NULL WHERE request_id=$1",
          [agreed.requestId]),
        /owner approval already consumed/
      );
      assert.equal(await reader.consume(agreed),false,
        "A used receipt must remain used even after a forged reset");
    });
  });
});
