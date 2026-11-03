import assert from "node:assert/strict";
import {createHash,generateKeyPairSync,randomBytes,randomUUID,sign} from "node:crypto";
import {test} from "node:test";
import {inIsolatedDatabase} from "./isolated-db.js";
import {PgPairingDeviceAPI} from "../src/pairing-device-api.js";
import {PgPairingReview} from "../src/pairing-review.js";
import {redemptionProof,pairingStatusProof} from "../src/device-pairing.js";
import {PgDeviceHandshakes} from "../src/device-handshake.js";

const conn=process.env.TEST_DATABASE_URL;
const secret="local-unit-test-secret-32-characters-minimum";
const migrations=[
  "001_inventory.pgsql","002_client_grants.pgsql",
  "007_device_pairing.pgsql","008_device_credentials.pgsql",
  "009_device_handshake.pgsql","011_pairing_review_budget.pgsql",
  "012_pairing_device_budget.pgsql"
];

test("approved pairing is consumed once by the authentic device key, enrolled disabled",
  {skip:!conn},async()=>{
  await inIsolatedDatabase(conn!,migrations,async pool=>{
    const a=new PgPairingDeviceAPI(pool,secret),b=new PgPairingDeviceAPI(pool,secret);
    const review=new PgPairingReview(pool,secret),owner="owner-b";
    const key=generateKeyPairSync("ed25519");
    const der=key.publicKey.export({format:"der",type:"spki"}) as Buffer;
    const issued=await a.issue("127.0.0.1","Physical KiCad",der);
    assert.equal(issued.kind,"ok");
    if(issued.kind!=="ok")return;
    const challenge=issued.data;
    const statusSignature=sign(null,pairingStatusProof(challenge.id,challenge.deviceCode),
      key.privateKey);
    assert.deepEqual(await a.approved("127.0.0.1",challenge.id,
      challenge.deviceCode,statusSignature),{kind:"ok",data:{approved:false}});
    assert.equal((await a.approved("127.0.0.1",challenge.id,
      randomBytes(32).toString("base64url"),statusSignature)).kind,"unavailable");
    const impostor=sign(null,pairingStatusProof(challenge.id,challenge.deviceCode),
      generateKeyPairSync("ed25519").privateKey);
    assert.equal((await a.approved("127.0.0.1",challenge.id,
      challenge.deviceCode,impostor)).kind,"unavailable");
    const proper=sign(null,redemptionProof(challenge.id,challenge.deviceCode),key.privateKey);
    const forged=sign(null,redemptionProof(challenge.id,challenge.deviceCode),
      generateKeyPairSync("ed25519").privateKey);
    assert.equal((await a.enroll("127.0.0.1",challenge.id,challenge.deviceCode,proper)).kind,"unavailable");
    assert.equal(await review.review(challenge.id,owner,challenge.userCode,"approve"),"approved");
    assert.deepEqual(await b.approved("127.0.0.1",challenge.id,
      challenge.deviceCode,statusSignature),{kind:"ok",data:{approved:true}});

    assert.equal((await a.enroll("127.0.0.1",challenge.id,challenge.deviceCode,forged)).kind,"unavailable");
    assert.equal((await a.enroll("127.0.0.1",challenge.id,
      randomBytes(32).toString("base64url"),proper)).kind,"unavailable");
    const both=await Promise.all([
      a.enroll("127.0.0.1",challenge.id,challenge.deviceCode,proper),
      b.enroll("127.0.0.1",challenge.id,challenge.deviceCode,proper)
    ]);
    assert.deepEqual(both.map(r=>r.kind).sort(),["ok","unavailable"]);
    const enrolled=both.find(r=>r.kind==="ok");
    if(!enrolled||enrolled.kind!=="ok")return;
    assert.equal(enrolled.data.kind,"enrolled");
    if(enrolled.data.kind!=="enrolled")return;
    const deviceId=enrolled.data.deviceId;
    const row=(await pool.query("SELECT d.enabled,d.owner_sub,c.revoked_at,c.key_fingerprint "+
      "FROM devices d JOIN device_credentials c ON c.device_id=d.id WHERE d.id=$1",
      [deviceId])).rows[0];
    assert.equal(row.enabled,false);
    assert.equal(row.owner_sub,owner);
    assert.equal(row.revoked_at,null);
    assert.equal(row.key_fingerprint,createHash("sha256").update(der).digest("hex"));
    assert.equal((await pool.query("SELECT count(*)::integer AS n FROM device_credentials "+
      "WHERE pairing_challenge_id=$1",[challenge.id])).rows[0].n,1);
    assert.equal((await pool.query("SELECT state FROM pairing_challenges WHERE id=$1",
      [challenge.id])).rows[0].state,"consumed");
    assert.equal((await new PgDeviceHandshakes(pool).issue(owner,deviceId)).kind,"unavailable");
    assert.deepEqual(await a.approved("127.0.0.1",challenge.id,
      challenge.deviceCode,statusSignature),{kind:"ok",data:{approved:false}});

    assert.equal((await b.enroll("127.0.0.1",challenge.id,challenge.deviceCode,proper)).kind,"unavailable");
  });
});

test("PostgreSQL multi-worker issuance budget prevents source and key replay flooding",
  {skip:!conn},async()=>{
  await inIsolatedDatabase(conn!,migrations,async pool=>{
    const a=new PgPairingDeviceAPI(pool,secret),b=new PgPairingDeviceAPI(pool,secret);
    const key=generateKeyPairSync("ed25519");
    const der=key.publicKey.export({format:"der",type:"spki"}) as Buffer;
    const attempts=await Promise.all(Array.from({length:12},(_,i)=>
      (i%2===0?a:b).issue("fixture-client-peer","KiCad Lab",der)));
    assert.equal(attempts.filter(x=>x.kind==="ok").length,3);
    assert.equal(attempts.filter(x=>x.kind==="throttled").length,9);
    const second=generateKeyPairSync("ed25519")
      .publicKey.export({format:"der",type:"spki"}) as Buffer;
    assert.equal((await a.issue("fixture-client-peer","Another KiCad",second)).kind,"throttled");
    const reset=await pool.query("UPDATE pairing_device_budget SET window_started_at="+
      "statement_timestamp()-interval '16 minutes'");
    assert.ok(reset.rowCount);
    assert.equal((await b.issue("fixture-client-peer","Another KiCad",second)).kind,"ok");
    const all=(await pool.query("SELECT * FROM pairing_device_budget")).rows;
    assert.ok(all.length>=3);
    assert.ok(all.every(row=>
      !JSON.stringify(row).includes("fixture-client-peer")&&
      !JSON.stringify(row).includes("KiCad Lab")));
  });
});

test("denied, nonexistent and expired approval cannot create a device",
  {skip:!conn},async()=>{
  await inIsolatedDatabase(conn!,migrations,async pool=>{
    const api=new PgPairingDeviceAPI(pool,secret),review=new PgPairingReview(pool,secret);
    const key=generateKeyPairSync("ed25519");
    const der=key.publicKey.export({format:"der",type:"spki"}) as Buffer;
    const denied=await api.issue("peer","Test workstation",der);
    assert.equal(denied.kind,"ok");
    if(denied.kind!=="ok")return;
    assert.equal(await review.review(denied.data.id,"owner",denied.data.userCode,"deny"),"denied");
    const signature=sign(null,redemptionProof(denied.data.id,denied.data.deviceCode),
      key.privateKey);
    assert.equal((await api.enroll("peer",denied.data.id,denied.data.deviceCode,signature)).kind,"unavailable");
    assert.equal((await api.enroll("peer",randomUUID(),denied.data.deviceCode,signature)).kind,"unavailable");
    const expired=await api.issue("peer","Test workstation 2",der);
    assert.equal(expired.kind,"ok");
    if(expired.kind!=="ok")return;
    await pool.query("UPDATE pairing_challenges SET "+
      "created_at=statement_timestamp()-interval '6 minutes',"+
      "expires_at=statement_timestamp()-interval '1 minute' WHERE id=$1",
      [expired.data.id]);
    assert.equal(await review.review(expired.data.id,"owner",expired.data.userCode,"approve"),"unavailable");
    assert.equal((await pool.query("SELECT state FROM pairing_challenges WHERE id=$1",
      [expired.data.id])).rows[0].state,"expired");
    assert.equal((await pool.query("SELECT count(*)::integer AS n FROM devices")).rows[0].n,0);
  });
});

test("unknown challenge attempts share an atomic redemption limit",
  {skip:!conn},async()=>{
  await inIsolatedDatabase(conn!,migrations,async pool=>{
    const a=new PgPairingDeviceAPI(pool,secret),b=new PgPairingDeviceAPI(pool,secret);
    const id=randomUUID(),code=randomBytes(32).toString("base64url");
    const signature=randomBytes(64);
    const result=await Promise.all(Array.from({length:13},(_,i)=>
      (i%2===0?a:b).enroll("shared-peer",id,code,signature)));
    assert.equal(result.filter(x=>x.kind==="unavailable").length,8);
    assert.equal(result.filter(x=>x.kind==="throttled").length,5);
    assert.equal((await pool.query("SELECT count(*)::integer AS n FROM devices")).rows[0].n,0);
  });
});

test("pairing device API fails closed when secret is too short",()=>{
  assert.throws(()=>new PgPairingDeviceAPI({} as never,"short"),/SECRET_TOO_SHORT/);
});
