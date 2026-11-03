import assert from "node:assert/strict";
import {createHmac,generateKeyPairSync,randomUUID} from "node:crypto";
import {test} from "node:test";
import {inIsolatedDatabase} from "./isolated-db.js";
import {PgPairingChallenges} from "../src/pairing-store.js";
import {PgPairingReview} from "../src/pairing-review.js";

const db=process.env.TEST_DATABASE_URL;
const secret="synthetic-better-auth-secret-minimum-32-characters";
test("Postgres rate budget serializes concurrent owners and resets after window",
  {skip:!db},async()=>{
  await inIsolatedDatabase(db!,[
    "001_inventory.pgsql","002_client_grants.pgsql",
    "007_device_pairing.pgsql","008_device_credentials.pgsql",
    "011_pairing_review_budget.pgsql"
  ],async pool=>{
    const a=new PgPairingReview(pool,secret),b=new PgPairingReview(pool,secret);
    const owner="owner-a",other="owner-b";
    const responses=await Promise.all(
      Array.from({length:20},(_,i)=>(i%2?a:b).review(
        randomUUID(),owner,"000000-000000","approve"))
    );
    assert.equal(responses.filter(x=>x==="throttled").length,10);
    assert.equal(responses.filter(x=>x==="unavailable").length,10);
    assert.equal((await pool.query(
      "SELECT attempts FROM pairing_review_budget WHERE owner_sub=$1",[owner]
    )).rows[0].attempts,11);
    assert.equal(await a.review(randomUUID(),other,"000000-000000","approve"),"unavailable");
    assert.equal((await pool.query(
      "SELECT attempts FROM pairing_review_budget WHERE owner_sub=$1",[other]
    )).rows[0].attempts,1);

    const derived=createHmac("sha256",secret)
      .update("kicad-cloud-pairing-user-code-v1").digest();
    const store=new PgPairingChallenges(pool,derived);
    const keys=generateKeyPairSync("ed25519");
    const der=keys.publicKey.export({format:"der",type:"spki"}) as Buffer;
    const pairing=await store.issue("Lab workstation",der);
    assert.equal(await a.review(pairing.id,owner,pairing.userCode,"approve"),"throttled");
    await pool.query(
      "UPDATE pairing_review_budget SET window_started_at=clock_timestamp()-interval '6 minutes' "+
      "WHERE owner_sub=$1",[owner]);
    assert.equal(await b.review(pairing.id,owner,pairing.userCode,"approve"),"approved");
    const approved=(await pool.query(
      "SELECT state,owner_sub FROM pairing_challenges WHERE id=$1",[pairing.id])).rows[0];
    assert.deepEqual(approved,{state:"approved",owner_sub:owner});
    assert.equal(await a.review(pairing.id,other,pairing.userCode,"approve"),"unavailable");

    // Failed-code attempts remain bounded by the challenge's own five-try lock.
    const brute=await store.issue("Another workstation",der);
    const wrong=await Promise.all([
      a.review(brute.id,owner,"111111-111111","deny"),
      b.review(brute.id,owner,"111111-111111","deny")
    ]);
    assert.deepEqual(wrong.sort(),["invalid_code","invalid_code"]);
    const attempts=(await pool.query(
      "SELECT attempts FROM pairing_challenges WHERE id=$1",[brute.id])).rows[0].attempts;
    assert.equal(attempts,2);
  });
});
test("short or missing auth secret never starts a pairing store",()=>{
  assert.throws(()=>new PgPairingReview({} as never,"short"),/SECRET_TOO_SHORT/);
});
