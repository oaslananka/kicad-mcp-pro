import assert from "node:assert/strict";
import {generateKeyPairSync,randomBytes,sign} from "node:crypto";
import {test} from "node:test";
import {inIsolatedDatabase} from "./isolated-db.js";
import {PgPairingChallenges} from "../src/pairing-store.js";
import {redemptionProof} from "../src/device-pairing.js";
import {PgConnectorSessions,connectorSessionProof,connectorEventProof}
  from "../src/connector-session.js";

const url=process.env.TEST_DATABASE_URL;
test("Postgres bound sessions serialize proof, signed events, expiry, close and revocation",
  {skip:!url},async()=>{
  await inIsolatedDatabase(url!, [
    "001_inventory.pgsql","002_client_grants.pgsql",
    "007_device_pairing.pgsql","008_device_credentials.pgsql",
    "009_device_handshake.pgsql","010_connector_sessions.pgsql"
  ],async db=>{
    const owner="owner-a",keys=generateKeyPairSync("ed25519");
    const publicKey=keys.publicKey.export({format:"der",type:"spki"}) as Buffer;
    const pair=new PgPairingChallenges(db,randomBytes(32));
    const sessionsA=new PgConnectorSessions(db),sessionsB=new PgConnectorSessions(db);
    const initial=await pair.issue("KiCad Lab",publicKey);
    assert.equal(await pair.review(initial.id,owner,initial.userCode,"approve"),"approved");
    const enrolled=await pair.enroll(initial.id,initial.deviceCode,sign(
      null,redemptionProof(initial.id,initial.deviceCode),keys.privateKey));
    assert.equal(enrolled.kind,"enrolled");
    if(enrolled.kind!=="enrolled")return;
    const device=enrolled.deviceId;
    assert.equal((await sessionsA.issue(owner,device)).kind,"unavailable");
    assert.equal((await sessionsA.issue("other-owner",device)).kind,"unavailable");
    assert.equal((await sessionsA.issue(owner,"invalid")).kind,"unavailable");
    // Simulate future authenticated owner enable; no enabling API exists.
    await db.query("UPDATE devices SET enabled=true WHERE id=$1",[device]);
    const first=await sessionsA.issue(owner,device);
    assert.equal(first.kind,"issued");
    if(first.kind!=="issued")return;
    assert.equal((await sessionsB.issue(owner,device)).kind,"unavailable");
    const pending=(await db.query("SELECT * FROM connector_sessions WHERE id=$1",
      [first.sessionId])).rows[0];
    assert.equal(pending.state,"pending");
    assert.equal(JSON.stringify(pending).includes(first.binding),false);
    const storedChallenge=(await db.query("SELECT * FROM device_handshake_challenges WHERE id=$1",
      [first.challengeId])).rows[0];
    assert.equal(JSON.stringify(storedChallenge).includes(first.nonce),false);

    const sessionPayload=connectorSessionProof(first.sessionId,first.challengeId,
      device,first.nonce,first.binding);
    const sig=sign(null,sessionPayload,keys.privateKey);
    const attacker=generateKeyPairSync("ed25519");
    const forged=sign(null,sessionPayload,attacker.privateKey);
    assert.equal((await sessionsA.activate(owner,device,first.sessionId,
      first.nonce,first.binding,forged)).kind,"unavailable");
    assert.equal((await sessionsA.activate(owner,device,first.sessionId,
      first.nonce,"invalid",sig)).kind,"unavailable");
    assert.equal((await sessionsA.activate("other-owner",device,first.sessionId,
      first.nonce,first.binding,sig)).kind,"unavailable");
    assert.equal((await sessionsA.activate(owner,device,first.sessionId,
      "invalid",first.binding,sig)).kind,"unavailable");
    const active=await Promise.all([
      sessionsA.activate(owner,device,first.sessionId,first.nonce,first.binding,sig),
      sessionsB.activate(owner,device,first.sessionId,first.nonce,first.binding,sig)
    ]);
    assert.deepEqual(active.map(x=>x.kind).sort(),["active","unavailable"]);
    assert.equal((await sessionsA.activate(owner,device,first.sessionId,
      first.nonce,first.binding,sig)).kind,"unavailable");

    const bytes=Buffer.from('{"type":"heartbeat"}',"utf8");
    const eventSignature=sign(null,connectorEventProof(
      first.sessionId,device,first.binding,1,bytes),keys.privateKey);
    const accepted=await Promise.all([
      sessionsA.verifyEvent(owner,device,first.sessionId,first.binding,1,bytes,eventSignature),
      sessionsB.verifyEvent(owner,device,first.sessionId,first.binding,1,bytes,eventSignature)
    ]);
    assert.deepEqual(accepted.map(x=>x.kind).sort(),["accepted","unavailable"]);
    assert.equal((await sessionsA.verifyEvent(owner,device,first.sessionId,
      first.binding,1,bytes,eventSignature)).kind,"unavailable");
    const seq2=2,bytes2=Buffer.from('{"type":"status"}',"utf8");
    const sig2=sign(null,connectorEventProof(
      first.sessionId,device,first.binding,seq2,bytes2),keys.privateKey);
    assert.equal((await sessionsA.verifyEvent(owner,device,first.sessionId,
      first.binding,seq2,Buffer.from('{"type":"tampered"}'),sig2)).kind,"unavailable");
    assert.equal((await sessionsA.verifyEvent(owner,device,first.sessionId,
      "invalid",seq2,bytes2,sig2)).kind,"unavailable");
    assert.equal((await sessionsA.verifyEvent("other-owner",device,first.sessionId,
      first.binding,seq2,bytes2,sig2)).kind,"unavailable");
    assert.equal((await sessionsA.verifyEvent(owner,device,first.sessionId,
      first.binding,3,bytes2,sig2)).kind,"unavailable");
    assert.equal((await sessionsB.verifyEvent(owner,device,first.sessionId,
      first.binding,seq2,bytes2,sig2)).kind,"accepted");
    const last=(await db.query("SELECT last_sequence FROM connector_sessions WHERE id=$1",
      [first.sessionId])).rows[0].last_sequence;
    assert.equal(Number(last),2);

    assert.equal(await sessionsA.close(owner,device,first.sessionId,"invalid"),false);
    assert.equal(await sessionsA.close(owner,device,first.sessionId,first.binding),true);
    assert.equal(await sessionsA.close(owner,device,first.sessionId,first.binding),false);
    const sig3=sign(null,connectorEventProof(
      first.sessionId,device,first.binding,3,bytes),keys.privateKey);
    assert.equal((await sessionsA.verifyEvent(owner,device,first.sessionId,
      first.binding,3,bytes,sig3)).kind,"unavailable");

    const pendingClose=await sessionsA.issue(owner,device);
    assert.equal(pendingClose.kind,"issued");
    if(pendingClose.kind!=="issued")return;
    assert.equal(await sessionsA.close(owner,device,pendingClose.sessionId,
      pendingClose.binding),true);
    assert.equal((await db.query(
      "SELECT status FROM device_handshake_challenges WHERE id=$1",
      [pendingClose.challengeId])).rows[0].status,"revoked");

    const expired=await sessionsA.issue(owner,device);
    assert.equal(expired.kind,"issued");
    if(expired.kind!=="issued")return;
    await db.query("UPDATE device_handshake_challenges SET "+
      "created_at=statement_timestamp()-interval '65 seconds',"+
      "expires_at=statement_timestamp()-interval '5 seconds' WHERE id=$1",
      [expired.challengeId]);
    const expiredSig=sign(null,connectorSessionProof(expired.sessionId,
      expired.challengeId,device,expired.nonce,expired.binding),keys.privateKey);
    assert.equal((await sessionsA.activate(owner,device,expired.sessionId,
      expired.nonce,expired.binding,expiredSig)).kind,"unavailable");
    assert.equal((await db.query("SELECT state FROM connector_sessions WHERE id=$1",
      [expired.sessionId])).rows[0].state,"expired");

    const final=await sessionsA.issue(owner,device);
    assert.equal(final.kind,"issued");
    if(final.kind!=="issued")return;
    const finalSig=sign(null,connectorSessionProof(final.sessionId,
      final.challengeId,device,final.nonce,final.binding),keys.privateKey);
    assert.equal((await sessionsA.activate(owner,device,final.sessionId,
      final.nonce,final.binding,finalSig)).kind,"active");
    assert.equal(await pair.revokeDevice(owner,device),true);
    assert.equal((await db.query("SELECT state FROM connector_sessions WHERE id=$1",
      [final.sessionId])).rows[0].state,"revoked");
    const revocationProof=sign(null,connectorEventProof(
      final.sessionId,device,final.binding,1,bytes),keys.privateKey);
    assert.equal((await sessionsA.verifyEvent(owner,device,final.sessionId,
      final.binding,1,bytes,revocationProof)).kind,"unavailable");
    assert.equal((await sessionsA.issue(owner,device)).kind,"unavailable");
  });
});
