import assert from "node:assert/strict";
import {randomUUID} from "node:crypto";
import {test} from "node:test";
import {PgWriteProofReservations} from "../src/connector-write-reservations.js";
import {inIsolatedDatabase} from "./isolated-db.js";

const url=process.env.TEST_DATABASE_URL;

test("write proposal replay reservation is strictly fail-closed offline",async()=>{
  const reservation=new PgWriteProofReservations({query:async()=>{throw Error("no database");}} as never);
  const session=randomUUID(),request=randomUUID();
  assert.equal(await reservation.reserveOnce(session,request,Date.now()+5000),false);
  assert.equal(await reservation.reserveOnce("bad",request,Date.now()+5000),false);
  assert.equal(await reservation.reserveOnce(session,"bad",Date.now()+5000),false);
  assert.equal(await reservation.reserveOnce(session,request,Number.NaN),false);
  assert.equal(await reservation.reserveOnce(session,request,Number.MAX_SAFE_INTEGER+1),false);
  assert.equal(await reservation.reserveOnce(session,request,0),false);
});

test("Postgres one-shot reservation serializes workers and blocks cross-session replay",
  {skip:!url},async()=>{
  await inIsolatedDatabase(url!,["020_connector_write_proof_reservations.pgsql"],async pool=>{
    const a=new PgWriteProofReservations(pool),b=new PgWriteProofReservations(pool);
    const session=randomUUID(),request=randomUUID(),deadline=Date.now()+8000;
    const outcomes=await Promise.all(Array.from({length:20},(_,i)=>
      (i%2===0?a:b).reserveOnce(session,request,deadline)));
    assert.equal(outcomes.filter(Boolean).length,1);
    assert.equal(await b.reserveOnce(session,request,deadline),false);
    assert.equal(await b.reserveOnce(randomUUID(),request,deadline),false,
      "request IDs must never be reused even under different sessions");
    assert.equal(await a.reserveOnce(session,randomUUID(),deadline),true);
    const rows=await pool.query("SELECT session_id,request_id FROM connector_write_proof_reservations");
    assert.equal(rows.rows.length,2);
    assert.equal(await a.reserveOnce(session,randomUUID(),Date.now()-1000),false);
    assert.equal(await a.reserveOnce(session,randomUUID(),Date.now()+30_000),false);
    assert.equal(await a.reserveOnce(session,"../../escape",Date.now()+5000),false);
  });
});
