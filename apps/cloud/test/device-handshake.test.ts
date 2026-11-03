import assert from "node:assert/strict";
import {generateKeyPairSync,randomBytes,randomUUID,sign} from "node:crypto";
import {readFile} from "node:fs/promises";
import {test} from "node:test";
import pg from "pg";
import {PgPairingChallenges} from "../src/pairing-store.js";
import {deviceHandshakeProof,PgDeviceHandshakes} from "../src/device-handshake.js";
import {redemptionProof} from "../src/device-pairing.js";

const url=process.env.TEST_DATABASE_URL;
test("PostgreSQL handshake single-use, expiry, lockout, owner scope and revocation races",
  {skip:!url},async()=>{
  const root=new pg.Pool({connectionString:url});
  const schema="handshake_"+randomBytes(7).toString("hex");
  let db:pg.Pool|undefined;
  try{
    await root.query('CREATE SCHEMA "'+schema+'"');
    const scoped=new URL(url!);
    scoped.searchParams.set("options","-c search_path="+schema);
    db=new pg.Pool({connectionString:scoped.toString(),max:8});
    for(const file of ["001_inventory.pgsql","002_client_grants.pgsql",
      "007_device_pairing.pgsql","008_device_credentials.pgsql",
      "009_device_handshake.pgsql","010_connector_sessions.pgsql"]){
      await db.query(await readFile(new URL("../db/"+file,import.meta.url),"utf8"));
    }
    const pair=new PgPairingChallenges(db,randomBytes(32));
    const handshakeA=new PgDeviceHandshakes(db),handshakeB=new PgDeviceHandshakes(db);
    const keys=generateKeyPairSync("ed25519");
    const publicKey=keys.publicKey.export({format:"der",type:"spki"}) as Buffer;
    const owner="owner-a";
    const initial=await pair.issue("Test KiCad",publicKey);
    assert.equal(await pair.review(initial.id,owner,initial.userCode,"approve"),"approved");
    const initialSignature=sign(null,redemptionProof(initial.id,initial.deviceCode),keys.privateKey);
    const enrollment=await pair.enroll(initial.id,initial.deviceCode,initialSignature);
    assert.equal(enrollment.kind,"enrolled");
    if(enrollment.kind!=="enrolled")return;
    const deviceId=enrollment.deviceId;

    assert.equal((await handshakeA.issue(owner,deviceId)).kind,"unavailable");
    assert.equal((await handshakeA.issue("foreign-owner",deviceId)).kind,"unavailable");
    assert.equal((await handshakeA.issue(owner,"invalid-uuid")).kind,"unavailable");
    // A separate authenticated owner-enable API is NOT implemented; fixture only.
    await db.query("UPDATE devices SET enabled=true WHERE id=$1",[deviceId]);
    const pending=await handshakeA.issue(owner,deviceId);
    assert.equal(pending.kind,"issued");
    if(pending.kind!=="issued")return;
    assert.equal((await handshakeB.issue(owner,deviceId)).kind,"unavailable");
    assert.equal(pending.nonce.length,43);
    const persisted=(await db.query("SELECT * FROM device_handshake_challenges WHERE id=$1",
      [pending.challengeId])).rows[0];
    assert.equal(persisted.status,"pending");
    assert.equal(persisted.failures,0);
    assert.equal(JSON.stringify(persisted).includes(pending.nonce),false);

    const legitimate=sign(null,
      deviceHandshakeProof(pending.challengeId,deviceId,pending.nonce),keys.privateKey);
    const attacker=generateKeyPairSync("ed25519");
    const wrongKey=sign(null,
      deviceHandshakeProof(pending.challengeId,deviceId,pending.nonce),attacker.privateKey);
    assert.equal((await handshakeA.verify(owner,deviceId,pending.challengeId,
      pending.nonce,wrongKey)).kind,"unavailable");
    assert.equal((await handshakeA.verify(owner,deviceId,pending.challengeId,
      "invalid",legitimate)).kind,"unavailable");
    assert.equal((await handshakeA.verify("foreign-owner",deviceId,pending.challengeId,
      pending.nonce,legitimate)).kind,"unavailable");
    assert.equal((await handshakeA.verify(owner,randomUUID(),pending.challengeId,
      pending.nonce,legitimate)).kind,"unavailable");

    const results=await Promise.all([
      handshakeA.verify(owner,deviceId,pending.challengeId,pending.nonce,legitimate),
      handshakeB.verify(owner,deviceId,pending.challengeId,pending.nonce,legitimate)
    ]);
    assert.deepEqual(results.map(x=>x.kind).sort(),["unavailable","verified"]);
    assert.equal((await handshakeB.verify(owner,deviceId,pending.challengeId,
      pending.nonce,legitimate)).kind,"unavailable");
    assert.equal((await db.query("SELECT status,failures FROM device_handshake_challenges "+
      "WHERE id=$1",[pending.challengeId])).rows[0].status,"verified");

    const second=await handshakeA.issue(owner,deviceId);
    assert.equal(second.kind,"issued");
    if(second.kind!=="issued")return;
    assert.equal((await handshakeA.verify(owner,deviceId,second.challengeId,
      pending.nonce,legitimate)).kind,"unavailable");
    assert.equal((await handshakeA.verify(owner,deviceId,second.challengeId,
      second.nonce,legitimate)).kind,"unavailable");
    for(let i=2;i<5;i++){
      assert.equal((await handshakeA.verify(owner,deviceId,second.challengeId,
        "invalid",legitimate)).kind,"unavailable");
    }
    assert.equal((await db.query("SELECT status,failures FROM device_handshake_challenges "+
      "WHERE id=$1",[second.challengeId])).rows[0].status,"failed");
    const validSecond=sign(null,deviceHandshakeProof(
      second.challengeId,deviceId,second.nonce),keys.privateKey);
    assert.equal((await handshakeA.verify(owner,deviceId,second.challengeId,
      second.nonce,validSecond)).kind,"unavailable");

    const expiry=await handshakeA.issue(owner,deviceId);
    assert.equal(expiry.kind,"issued");
    if(expiry.kind!=="issued")return;
    await db.query("UPDATE device_handshake_challenges SET "+
      "created_at=statement_timestamp()-interval '50 seconds', "+
      "expires_at=statement_timestamp()-interval '1 second' WHERE id=$1",
      [expiry.challengeId]);
    const expiredSignature=sign(null,deviceHandshakeProof(
      expiry.challengeId,deviceId,expiry.nonce),keys.privateKey);
    assert.equal((await handshakeA.verify(owner,deviceId,expiry.challengeId,
      expiry.nonce,expiredSignature)).kind,"unavailable");
    assert.equal((await db.query("SELECT status FROM device_handshake_challenges "+
      "WHERE id=$1",[expiry.challengeId])).rows[0].status,"expired");

    const race=await handshakeA.issue(owner,deviceId);
    assert.equal(race.kind,"issued");
    if(race.kind!=="issued")return;
    const raceSignature=sign(null,deviceHandshakeProof(
      race.challengeId,deviceId,race.nonce),keys.privateKey);
    const [proofResult,revokeResult]=await Promise.all([
      handshakeA.verify(owner,deviceId,race.challengeId,race.nonce,raceSignature),
      pair.revokeDevice(owner,deviceId)
    ]);
    assert.ok(["verified","unavailable"].includes(proofResult.kind));
    assert.equal(revokeResult,true);
    assert.equal((await handshakeA.issue(owner,deviceId)).kind,"unavailable");
    assert.equal((await handshakeA.verify(owner,deviceId,race.challengeId,
      race.nonce,raceSignature)).kind,"unavailable");
    assert.equal(await pair.activeDevicePublicKey(owner,deviceId),null);
    const raceStatus=(await db.query(
      "SELECT status FROM device_handshake_challenges WHERE id=$1",[race.challengeId])).rows[0].status;
    assert.ok(["verified","revoked"].includes(raceStatus));

    // Deterministic deny-after-revoke, including a formerly valid nonce
    // and a correct signature, on a separate enrolled device.
    const newKeys=generateKeyPairSync("ed25519");
    const nextKey=newKeys.publicKey.export({format:"der",type:"spki"}) as Buffer;
    const nextPairing=await pair.issue("Revocation Check",nextKey);
    assert.equal(await pair.review(nextPairing.id,owner,nextPairing.userCode,"approve"),"approved");
    const nextEnrollment=await pair.enroll(
      nextPairing.id,nextPairing.deviceCode,
      sign(null,redemptionProof(nextPairing.id,nextPairing.deviceCode),newKeys.privateKey));
    assert.equal(nextEnrollment.kind,"enrolled");
    if(nextEnrollment.kind!=="enrolled")return;
    await db.query("UPDATE devices SET enabled=true WHERE id=$1",[nextEnrollment.deviceId]);
    const outstanding=await handshakeA.issue(owner,nextEnrollment.deviceId);
    assert.equal(outstanding.kind,"issued");
    if(outstanding.kind!=="issued")return;
    const validOutstanding=sign(null,deviceHandshakeProof(
      outstanding.challengeId,nextEnrollment.deviceId,outstanding.nonce),newKeys.privateKey);
    assert.equal(await pair.revokeDevice(owner,nextEnrollment.deviceId),true);
    const status=(await db.query(
      "SELECT status FROM device_handshake_challenges WHERE id=$1",
      [outstanding.challengeId])).rows[0]?.status;
    assert.equal(status,"revoked");
    assert.equal((await handshakeA.verify(owner,nextEnrollment.deviceId,
      outstanding.challengeId,outstanding.nonce,validOutstanding)).kind,"unavailable");
  }finally{
    await db?.end();
    await root.query('DROP SCHEMA IF EXISTS "'+schema+'" CASCADE');
    await root.end();
  }
});
