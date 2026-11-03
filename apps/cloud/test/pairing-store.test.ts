import assert from "node:assert/strict";
import {randomBytes,generateKeyPairSync,sign} from "node:crypto";
import {readFile} from "node:fs/promises";
import {test} from "node:test";
import pg from "pg";
import {PgPairingChallenges} from "../src/pairing-store.js";
import {redemptionProof,MAX_USER_CODE_ATTEMPTS} from "../src/device-pairing.js";

const url=process.env.TEST_DATABASE_URL;
test("isolated PostgreSQL pairing transitions serialize competing workers",
  {skip:!url},async()=>{
  const admin=new pg.Pool({connectionString:url});
  const schema="pairing_"+randomBytes(8).toString("hex");
  let pool:pg.Pool|undefined;
  try{
    await admin.query('CREATE SCHEMA "'+schema+'"');
    const scoped=new URL(url!);
    scoped.searchParams.set("options","-c search_path="+schema);
    pool=new pg.Pool({connectionString:scoped.toString(),max:6});
    const sql=await readFile(new URL("../db/007_device_pairing.pgsql",import.meta.url),"utf8");
    await pool.query(await readFile(new URL("../db/001_inventory.pgsql",import.meta.url),"utf8"));
    await pool.query(await readFile(new URL("../db/002_client_grants.pgsql",import.meta.url),"utf8"));
    await pool.query(sql);
    await pool.query(await readFile(new URL("../db/008_device_credentials.pgsql",import.meta.url),"utf8"));
    const pair=generateKeyPairSync("ed25519");
    const der=pair.publicKey.export({format:"der",type:"spki"}) as Buffer;
    const store=new PgPairingChallenges(pool,randomBytes(32));
    const first=await store.issue("Prototype PC",der);
    const raw=(await pool.query("SELECT * FROM pairing_challenges WHERE id=$1",[first.id])).rows[0];
    assert.equal(raw.state,"pending");
    assert.equal(raw.owner_sub,null);
    assert.equal(JSON.stringify(raw).includes(first.deviceCode),false);
    assert.equal(JSON.stringify(raw).includes(first.userCode),false);
    const proof=sign(null,redemptionProof(first.id,first.deviceCode),pair.privateKey);
    assert.equal((await store.enroll(first.id,first.deviceCode,proof)).kind,"unavailable");

    const approvals=await Promise.all([
      store.review(first.id,"owner-1",first.userCode,"approve"),
      store.review(first.id,"owner-2",first.userCode,"approve")
    ]);
    assert.deepEqual(approvals.sort(),["approved","unavailable"]);
    const owner=(await pool.query("SELECT owner_sub FROM pairing_challenges WHERE id=$1",[first.id])).rows[0].owner_sub;
    assert.ok(["owner-1","owner-2"].includes(owner));

    const redeemed=await Promise.all([
      store.enroll(first.id,first.deviceCode,proof),
      store.enroll(first.id,first.deviceCode,proof)
    ]);
    assert.deepEqual(redeemed.map(r=>r.kind).sort(),["enrolled","unavailable"]);
    assert.equal(redeemed.find(r=>r.kind==="enrolled")?.ownerSub,owner);
    assert.equal((await pool.query("SELECT state FROM pairing_challenges WHERE id=$1",[first.id])).rows[0].state,"consumed");
    const linked=await pool.query(
      "SELECT d.enabled,c.pairing_challenge_id FROM devices d "+
      "JOIN device_credentials c ON c.device_id=d.id WHERE c.pairing_challenge_id=$1",
      [first.id]);
    assert.equal(linked.rows.length,1);
    assert.equal(linked.rows[0].enabled,false);
    assert.equal((await store.enroll(first.id,first.deviceCode,proof)).kind,"unavailable");

    const wrong=await store.issue("Locked PC",der);
    const results=await Promise.all(Array.from({length:MAX_USER_CODE_ATTEMPTS},()=>(
      store.review(wrong.id,"owner-1","IIIIII-IIIIII","approve")
    )));
    assert.equal(results.filter(r=>r==="invalid_code").length,MAX_USER_CODE_ATTEMPTS-1);
    assert.equal(results.filter(r=>r==="locked").length,1);
    const locked=(await pool.query("SELECT state,attempts FROM pairing_challenges WHERE id=$1",[wrong.id])).rows[0];
    assert.equal(locked.state,"locked");
    assert.equal(locked.attempts,MAX_USER_CODE_ATTEMPTS);
    assert.equal(await store.review(wrong.id,"owner-1",wrong.userCode,"approve"),"unavailable");

    const denied=await store.issue("Denied PC",der);
    assert.equal(await store.review(denied.id,"owner-3",denied.userCode,"deny"),"denied");
    assert.equal(await store.review(denied.id,"owner-3",denied.userCode,"approve"),"unavailable");

    const expired=await store.issue("Expired PC",der);
    await pool.query("UPDATE pairing_challenges SET "+
      "created_at=statement_timestamp()-interval '5 minutes 1 second',"+
      "expires_at=statement_timestamp()-interval '1 second' WHERE id=$1",[expired.id]);
    assert.equal(await store.review(expired.id,"owner-1",expired.userCode,"approve"),"unavailable");
    assert.equal((await pool.query("SELECT state FROM pairing_challenges WHERE id=$1",[expired.id])).rows[0].state,"expired");
    assert.equal((await store.enroll("not-a-uuid",first.deviceCode,proof)).kind,"unavailable");

    // SQL constraints must not allow state/owner or attempt-counter corruption.
    await assert.rejects(pool.query("UPDATE pairing_challenges SET state='approved' WHERE id=$1",[wrong.id]));
    await assert.rejects(pool.query("UPDATE pairing_challenges SET attempts=6 WHERE id=$1",[wrong.id]));
  }finally{
    await pool?.end();
    await admin.query('DROP SCHEMA IF EXISTS "'+schema+'" CASCADE');
    await admin.end();
  }
});
