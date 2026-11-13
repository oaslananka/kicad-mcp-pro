import assert from "node:assert/strict";
import {test} from "node:test";
import pg from "pg";
import {PgManagedReadAccess} from "../src/connector-managed-read-access.js";
import {inIsolatedDatabase} from "./isolated-db.js";

const device="8b85d574-ce89-458b-8b25-50703cbaec36";
const project="a8f4c3f0-d763-45b8-b153-53df8c637421";
const client="cloud-test-client";
const owner="cloud-test-owner";
const oauth={ownerSub:owner,clientId:client,accessTokenIssuedAtSeconds:Math.floor(Date.now()/1000)};
const migrations=[
  "001_inventory.pgsql","002_client_grants.pgsql",
  "007_device_pairing.pgsql","008_device_credentials.pgsql",
  "019_connector_managed_read_access.pgsql",
  "021_connector_managed_native_operations.pgsql"
];

test("invalid native operations and identities never consult SQL",async()=>{
  const store=new PgManagedReadAccess({
    query:async()=>{throw Error("unexpected database query");}
  } as unknown as pg.Pool);
  assert.equal(await store.setNativeOperation(owner,device,project,
    "project_summary" as never,true),false);
  assert.equal(await store.setNativeOperation(owner,device,project,
    "run_erc" as never,true),false);
  assert.equal(await store.setNativeOperation(owner,"bad",project,"run_drc",true),false);
  assert.equal(await store.isEnabled(oauth,device,project,"run_erc" as never),false);
  assert.equal(await store.isEnabled(oauth,"bad",project,"run_drc"),false);
});

test("owner native operations require distinct explicit grant, with no resurrection",
  {skip:!process.env.TEST_DATABASE_URL},async()=>{
  await inIsolatedDatabase(process.env.TEST_DATABASE_URL!,migrations,async db=>{
    await db.query("INSERT INTO devices(id,owner_sub,alias,enabled) VALUES($1,$2,'Test',true)",
      [device,owner]);
    await db.query("INSERT INTO projects(id,owner_sub,device_id,alias,enabled,max_mode) "+
      "VALUES($1,$2,$3,'Test',true,'readonly')",[project,owner,device]);
    await db.query("INSERT INTO pairing_challenges(id,device_alias,device_public_key_der,"+
      "device_fingerprint,user_code_mac,device_code_mac,expires_at,state,owner_sub) "+
      "VALUES($1,'Test',repeat('A',40),repeat('a',64),repeat('b',64),repeat('c',64),"+
      "clock_timestamp()+interval '1 minute','consumed',$2)",
      ["11a87bc9-4b16-4a1a-a957-5858498cbcdc",owner]);
    await db.query("INSERT INTO device_credentials(device_id,owner_sub,public_key_der,"+
      "key_fingerprint,pairing_challenge_id) VALUES($1,$2,repeat('A',40),repeat('d',64),$3)",
      [device,owner,"11a87bc9-4b16-4a1a-a957-5858498cbcdc"]);
    await db.query("INSERT INTO project_client_grants(project_id,owner_sub,client_id,enabled,"+
      "max_mode) VALUES($1,$2,$3,true,'readonly')",[project,owner,client]);
    const policy=new PgManagedReadAccess(db);
    assert.equal(await policy.isEnabled(oauth,device,project,"run_drc"),false);
    assert.equal(await policy.setNativeOperation(owner,device,project,"run_drc",true),false,
      "A native operation cannot be enabled before the project read switch is on");
    assert.equal(await policy.setEnabled(owner,device,project,true),true);
    assert.equal(await policy.isEnabled(oauth,device,project,"project_summary"),true);
    assert.equal(await policy.isEnabled(oauth,device,project,"run_drc"),false,
      "Summary permission must not silently grant native reads");
    assert.equal(await policy.setNativeOperation("foreign-owner",device,project,"run_drc",true),false);
    assert.equal(await policy.setNativeOperation(owner,device,project,"run_drc",true),true);
    assert.equal(await policy.setNativeOperation(owner,device,project,"run_drc",true),true);
    assert.equal(await policy.isEnabled(oauth,device,project,"run_drc"),true);
    assert.equal(await policy.isEnabled(oauth,device,project,"project_board_counts"),false,
      "Native operations are independently scoped");
    const ops=await db.query<{native_operations:string[]}>(
      "SELECT native_operations FROM connector_managed_read_access WHERE project_id=$1",[project]);
    assert.deepEqual(ops.rows[0]?.native_operations,["run_drc"],
      "Duplicate grants must not accumulate");
    await db.query("UPDATE device_credentials SET revoked_at=clock_timestamp() WHERE device_id=$1",
      [device]);
    assert.equal(await policy.isEnabled(oauth,device,project,"run_drc"),false,
      "Device revocation immediately denies native operations");
    assert.equal(await policy.setNativeOperation(owner,device,project,"run_drc",true),false);
    await db.query("UPDATE device_credentials SET revoked_at=NULL WHERE device_id=$1",[device]);
    assert.equal(await policy.setEnabled(owner,device,project,false),true);
    assert.equal(await policy.isEnabled(oauth,device,project,"run_drc"),false);
    assert.equal(await policy.setEnabled(owner,device,project,true),true);
    assert.equal(await policy.isEnabled(oauth,device,project,"run_drc"),false,
      "Pausing and resuming project access cannot restore old native grants");
  });
});