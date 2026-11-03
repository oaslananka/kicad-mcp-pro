import assert from "node:assert/strict";
import {randomUUID} from "node:crypto";
import {test} from "node:test";
import {inIsolatedDatabase} from "./isolated-db.js";
import {pruneExpiredMetadata} from "../src/retention.js";

const conn=process.env.TEST_DATABASE_URL;
const migrations=[
  "001_inventory.pgsql","002_client_grants.pgsql",
  "007_device_pairing.pgsql","008_device_credentials.pgsql",
  "009_device_handshake.pgsql","010_connector_sessions.pgsql",
  "011_pairing_review_budget.pgsql","012_pairing_device_budget.pgsql"
];
type FixtureIds={
  oldSession:string;currentSession:string;oldHandshake:string;
  linkedHandshake:string;oldPairing:string;credentialPairing:string;
  freshPairing:string;oldBudget:string;freshBudget:string;
};
function digest(char:string):string{return char.repeat(64);}
async function fixture(db:import("pg").Pool):Promise<FixtureIds>{
  const oldDevice=randomUUID(),freshDevice=randomUUID();
  await db.query(
    "INSERT INTO devices(id,owner_sub,alias,enabled) VALUES "+
    "($1,'owner-old','Old Device',false),($2,'owner-new','New Device',true)",
    [oldDevice,freshDevice]
  );
  const oldPairing=randomUUID(),credentialPairing=randomUUID(),freshPairing=randomUUID();
  await db.query(
    "INSERT INTO pairing_challenges "+
    "(id,device_alias,device_public_key_der,device_fingerprint,user_code_mac,"+
    "device_code_mac,created_at,expires_at,state,owner_sub) VALUES "+
    "($1,'Old expired',repeat('Z',64),repeat('a',64),repeat('b',64),repeat('c',64),"+
    "statement_timestamp()-interval '40 days',"+
    "statement_timestamp()-interval '40 days'+interval '3 minutes','expired',NULL),"+
    "($2,'Linked',repeat('Z',64),repeat('d',64),repeat('e',64),repeat('f',64),"+
    "statement_timestamp()-interval '40 days',"+
    "statement_timestamp()-interval '40 days'+interval '3 minutes','consumed','owner-old'),"+
    "($3,'Fresh pending',repeat('Z',64),repeat('1',64),repeat('2',64),repeat('3',64),"+
    "statement_timestamp(),statement_timestamp()+interval '4 minutes','pending',NULL)",
    [oldPairing,credentialPairing,freshPairing]
  );
  await db.query(
    "INSERT INTO device_credentials(device_id,owner_sub,public_key_der,"+
    "key_fingerprint,pairing_challenge_id) "+
    "VALUES($1,'owner-old',repeat('Z',64),repeat('d',64),$2)",
    [oldDevice,credentialPairing]
  );
  const oldHandshake=randomUUID(),linkedHandshake=randomUUID();
  await db.query(
    "INSERT INTO device_handshake_challenges "+
    "(id,device_id,owner_sub,nonce_sha256,created_at,expires_at,status) VALUES "+
    "($1,$3,'owner-old',repeat('4',64),"+
    "statement_timestamp()-interval '40 days',"+
    "statement_timestamp()-interval '40 days'+interval '45 seconds','expired'),"+
    "($2,$4,'owner-new',repeat('5',64),"+
    "statement_timestamp(),statement_timestamp()+interval '45 seconds','pending')",
    [oldHandshake,linkedHandshake,oldDevice,freshDevice]
  );
  const oldSession=randomUUID(),currentSession=randomUUID();
  await db.query(
    "INSERT INTO connector_sessions "+
    "(id,device_id,owner_sub,handshake_id,connection_digest,created_at,expires_at,state) VALUES "+
    "($1,$3,'owner-old',$5,repeat('6',64),"+
    "statement_timestamp()-interval '40 days',"+
    "statement_timestamp()-interval '40 days'+interval '4 minutes','closed'),"+
    "($2,$4,'owner-new',$6,repeat('7',64),"+
    "statement_timestamp(),statement_timestamp()+interval '4 minutes','active')",
    [oldSession,currentSession,oldDevice,freshDevice,oldHandshake,linkedHandshake]
  );
  const oldBudget="a".repeat(64),freshBudget="b".repeat(64);
  await db.query(
    "INSERT INTO pairing_review_budget(owner_sub,window_started_at,attempts) VALUES "+
    "('stale-owner',statement_timestamp()-interval '2 days',9),"+
    "('current-owner',statement_timestamp()-interval '3 minutes',10)"
  );
  await db.query(
    "INSERT INTO pairing_device_budget(budget_key,window_started_at,attempts) VALUES "+
    "($1,statement_timestamp()-interval '2 days',41),"+
    "($2,statement_timestamp()-interval '10 minutes',40)",
    [oldBudget,freshBudget]
  );
  return {oldSession,currentSession,oldHandshake,linkedHandshake,oldPairing,
    credentialPairing,freshPairing,oldBudget,freshBudget};
}
async function count(db:import("pg").Pool,table:string):Promise<number>{
  // Only constant SQL text is allowed, including in test utilities.
  let sql: string;
  switch(table){
    case "connector_sessions": sql="SELECT count(*)::integer AS n FROM connector_sessions";break;
    case "device_handshake_challenges": sql="SELECT count(*)::integer AS n FROM device_handshake_challenges";break;
    case "pairing_challenges": sql="SELECT count(*)::integer AS n FROM pairing_challenges";break;
    case "pairing_review_budget": sql="SELECT count(*)::integer AS n FROM pairing_review_budget";break;
    case "pairing_device_budget": sql="SELECT count(*)::integer AS n FROM pairing_device_budget";break;
    default: throw new Error("invalid table");
  }
  const result=await db.query<{n:number}>(sql);
  return result.rows[0]?.n??0;
}
test("dry run never mutates; apply respects FK dependencies and original grace windows",
  {skip:!conn},async()=>{
  await inIsolatedDatabase(conn!,migrations,async db=>{
    const f=await fixture(db);
    const before=Object.fromEntries(await Promise.all(
      ["connector_sessions","device_handshake_challenges","pairing_challenges",
        "pairing_review_budget","pairing_device_budget"].map(async t=>[t,await count(db,t)])));
    const scan=await pruneExpiredMetadata(db,"dry-run");
    assert.equal(scan.mode,"dry-run");
    assert.equal(scan.tables.connector_sessions.eligible,1);
    assert.equal(scan.tables.device_handshake_challenges.eligible,0); // linked until session removal
    assert.equal(scan.tables.pairing_challenges.eligible,1); // bound credential survives
    assert.equal(scan.tables.pairing_review_budget.eligible,1);
    assert.equal(scan.tables.pairing_device_budget.eligible,1);
    for(const t of Object.keys(before))assert.equal(await count(db,t),before[t]);
    const applied=await pruneExpiredMetadata(db,"apply");
    assert.equal(applied.tables.connector_sessions.deleted,1);
    assert.equal(applied.tables.device_handshake_challenges.deleted,1);
    assert.equal(applied.tables.pairing_challenges.deleted,1);
    assert.equal(applied.tables.pairing_review_budget.deleted,1);
    assert.equal(applied.tables.pairing_device_budget.deleted,1);
    assert.equal(await count(db,"connector_sessions"),1);
    assert.equal(await count(db,"device_handshake_challenges"),1);
    assert.equal(await count(db,"pairing_challenges"),2);
    assert.equal(await count(db,"pairing_review_budget"),1);
    assert.equal(await count(db,"pairing_device_budget"),1);
    assert.equal((await db.query("SELECT count(*)::integer AS n FROM device_credentials "+
      "WHERE pairing_challenge_id=$1",[f.credentialPairing])).rows[0].n,1);
    assert.equal((await db.query("SELECT count(*)::integer AS n FROM connector_sessions "+
      "WHERE id=$1",[f.currentSession])).rows[0].n,1);
    assert.equal((await db.query("SELECT count(*)::integer AS n FROM device_handshake_challenges "+
      "WHERE id=$1",[f.linkedHandshake])).rows[0].n,1);
    assert.equal((await db.query("SELECT count(*)::integer AS n FROM pairing_challenges "+
      "WHERE id=$1",[f.freshPairing])).rows[0].n,1);
    assert.equal((await db.query("SELECT attempts FROM pairing_review_budget "+
      "WHERE owner_sub='current-owner'")).rows[0].attempts,10);
    assert.equal((await db.query("SELECT attempts FROM pairing_device_budget "+
      "WHERE budget_key=$1",[f.freshBudget])).rows[0].attempts,40);
    const repeated=await pruneExpiredMetadata(db,"apply");
    assert.ok(Object.values(repeated.tables).every(t=>t.deleted===0));
  });
});
test("bounded 100-row batches and concurrent workers never double-delete",
  {skip:!conn},async()=>{
  await inIsolatedDatabase(conn!,migrations,async db=>{
    await db.query("INSERT INTO pairing_device_budget(budget_key,window_started_at,attempts) "+
      "SELECT lpad(to_hex(x),64,'0'),"+
      "statement_timestamp()-interval '3 days',1 FROM generate_series(1,235) AS x");
    const initial=await pruneExpiredMetadata(db,"dry-run");
    assert.equal(initial.tables.pairing_device_budget.eligible,100);
    assert.equal(initial.tables.pairing_device_budget.hasMore,true);
    assert.equal(initial.tables.pairing_device_budget.deleted,0);
    const concurrent=await Promise.all([
      pruneExpiredMetadata(db,"apply"),
      pruneExpiredMetadata(db,"apply")
    ]);
    assert.ok(concurrent.every(x=>x.tables.pairing_device_budget.deleted<=100));
    const removed=concurrent.reduce((sum,v)=>sum+v.tables.pairing_device_budget.deleted,0);
    assert.ok(removed>=100&&removed<=200);
    assert.equal(await count(db,"pairing_device_budget"),235-removed);
    const final=await pruneExpiredMetadata(db,"apply");
    assert.equal(final.tables.pairing_device_budget.deleted,235-removed);
    assert.equal(await count(db,"pairing_device_budget"),0);
  });
});
test("retention action cannot silently switch to deletion",async()=>{
  await assert.rejects(pruneExpiredMetadata({} as never,"invalid" as never),/INVALID_RETENTION_ACTION/);
});
