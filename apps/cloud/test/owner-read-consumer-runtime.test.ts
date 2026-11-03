import assert from "node:assert/strict";
import {randomBytes,randomUUID} from "node:crypto";
import {test} from "node:test";
import {Pool} from "pg";
import {inIsolatedDatabase} from "./isolated-db.js";
import {openOwnerConsentRuntime} from "../src/owner-read-consumer-runtime.js";

const url=process.env.TEST_DATABASE_URL;
const owner="cloud-owner-fixture",client="cloud-client-fixture";
const origin="https://cloud.test.invalid";
const scope=()=>({
  oauth:{ownerSub:owner,clientId:client,
    accessTokenIssuedAtSeconds:Math.floor(Date.now()/1000)},
  requestId:randomUUID(),deviceId:randomUUID(),projectId:randomUUID(),
  origin,operation:"project_summary" as const,
  expiresAtUnixMs:Date.now()+20_000
});

test("owner-consent runtime is off by default and refuses unsafe activation",async()=>{
  const inactive=await openOwnerConsentRuntime({},origin,false,null);
  assert.equal(inactive,null);
  assert.equal(await openOwnerConsentRuntime({
    OWNER_READ_CONSUMER_ENABLED:"false"
  },origin,false,null),null);
  await assert.rejects(openOwnerConsentRuntime({
    OWNER_READ_CONSUMER_ENABLED:"yes"
  },origin,true,null),/Invalid owner-consent consumer setting/);
  await assert.rejects(openOwnerConsentRuntime({
    OWNER_READ_CONSUMER_ENABLED:"true"
  },origin,false,null),/requires HTTPS WebSocket transport/);
  await assert.rejects(openOwnerConsentRuntime({
    OWNER_READ_CONSUMER_ENABLED:"true"
  },"http://localhost",true,null),/requires HTTPS WebSocket transport/);
});

test("dedicated restricted SQL login can only consume independently issued one-shot receipt",
  {skip:!url,timeout:55_000},async()=>{
  await inIsolatedDatabase(url!,[
    "013_owner_read_approvals.pgsql","014_owner_read_approval_replay_guard.pgsql"
  ],async admin=>{
    const schema=(await admin.query<{schema:string}>(
      "SELECT current_schema() AS schema")).rows[0]?.schema;
    assert.match(schema??"",/^fixture_[a-f0-9]{18}$/);
    const password=randomBytes(32).toString("base64url");
    // Never embed a generated credential directly in query source or output.
    const roleSql=await admin.query<{statement:string}>(
      "SELECT format('CREATE ROLE cloud_receipt_runtime_fixture LOGIN PASSWORD %L',"+
      "$1::text) AS statement",[password]);
    await admin.query(roleSql.rows[0]!.statement);
    let runtime:Awaited<ReturnType<typeof openOwnerConsentRuntime>>=null;
    try{
      await admin.query(
        "DO $r$ BEGIN EXECUTE format("+
        "'GRANT USAGE ON SCHEMA %I TO cloud_receipt_runtime_fixture',"+
        "current_schema()); END $r$");
      await admin.query(
        "GRANT SELECT ON owner_read_approvals TO cloud_receipt_runtime_fixture");
      await admin.query(
        "GRANT UPDATE(consumed_at) ON owner_read_approvals TO cloud_receipt_runtime_fixture");
      const restrictedUrl=new URL(url!);
      restrictedUrl.username="cloud_receipt_runtime_fixture";
      restrictedUrl.password=password;
      restrictedUrl.searchParams.set("options","-c search_path="+schema);
      const env={
        OWNER_READ_CONSUMER_ENABLED:"true",
        OWNER_READ_CONSUMER_DATABASE_URL:restrictedUrl.toString()
      };
      await assert.rejects(openOwnerConsentRuntime({
        OWNER_READ_CONSUMER_ENABLED:"true"
      },origin,true,admin),/Missing independent/);
      await assert.rejects(openOwnerConsentRuntime({
        OWNER_READ_CONSUMER_ENABLED:"true",
        OWNER_READ_CONSUMER_DATABASE_URL:url!
      },origin,true,admin),/startup denied/,
      "Application's own table-owner role cannot consume approvals");
      runtime=await openOwnerConsentRuntime(env,origin,true,admin);
      assert.ok(runtime);
      const grant=scope();
      assert.equal(await runtime.consent.consume(grant),false,
        "An OAuth token or prepared intent cannot mint an owner approval");
      await admin.query(
        "INSERT INTO owner_read_approvals "+
        "(request_id,owner_sub,client_id,device_id,project_id,"+
        "cloud_origin,operation,expires_at) "+
        "VALUES($1,$2,$3,$4,$5,$6,$7,to_timestamp($8::double precision/1000))",
        [grant.requestId,grant.oauth.ownerSub,grant.oauth.clientId,
          grant.deviceId,grant.projectId,grant.origin,grant.operation,
          grant.expiresAtUnixMs]
      );
      const requests=await Promise.all(Array.from({length:5},
        ()=>runtime!.consent.consume(grant)));
      assert.equal(requests.filter(Boolean).length,1,
        "Concurrent Cloud readers cannot consume the same decision twice");
      assert.equal(await runtime.consent.consume(grant),false);
      await runtime.close();runtime=null;
      await admin.query(
        "GRANT UPDATE(owner_sub) ON owner_read_approvals TO cloud_receipt_runtime_fixture");
      await assert.rejects(openOwnerConsentRuntime(env,origin,true,admin),
        /startup denied/,
        "A consumer that can rewrite receipt identity must fail startup");
    }finally{
      await runtime?.close();
      await admin.query("DROP OWNED BY cloud_receipt_runtime_fixture");
      await admin.query("DROP ROLE cloud_receipt_runtime_fixture");
    }
  });
});
