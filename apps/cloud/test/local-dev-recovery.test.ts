import assert from "node:assert/strict";
import {generateKeyPairSync,randomBytes,sign} from "node:crypto";
import {test} from "node:test";
import {inIsolatedDatabase} from "./isolated-db.js";
import {PgPairingChallenges} from "../src/pairing-store.js";
import {redemptionProof} from "../src/device-pairing.js";
import {PgConnectorSessions,connectorSessionProof} from "../src/connector-session.js";
import {recoverLocalDevSessions} from "../src/local-dev-recovery.js";

test("sandbox restart closes only synthetic owner's old sessions; real owners remain active",{
  skip:!process.env.TEST_DATABASE_URL
},async()=>{
  await inIsolatedDatabase(process.env.TEST_DATABASE_URL!,[
    "001_inventory.pgsql","007_device_pairing.pgsql","008_device_credentials.pgsql",
    "009_device_handshake.pgsql","010_connector_sessions.pgsql"
  ],async db=>{
    const pairing=new PgPairingChallenges(db,randomBytes(32));
    const sessions=new PgConnectorSessions(db);
    const created:Record<string,{device:string;sessionId:string}>={};
    for(const owner of ["local-dev-owner","other-owner"]){
      const key=generateKeyPairSync("ed25519");
      const challenge=await pairing.issue("Developer computer",
        key.publicKey.export({format:"der",type:"spki"}) as Buffer);
      assert.equal(await pairing.review(challenge.id,owner,challenge.userCode,"approve"),"approved");
      const enrolled=await pairing.enroll(challenge.id,challenge.deviceCode,
        sign(null,redemptionProof(challenge.id,challenge.deviceCode),key.privateKey));
      assert.equal(enrolled.kind,"enrolled");
      if(enrolled.kind!=="enrolled")throw Error("enrollment failed");
      await db.query("UPDATE devices SET enabled=true WHERE id=$1",[enrolled.deviceId]);
      const s=await sessions.issue(owner,enrolled.deviceId);
      assert.equal(s.kind,"issued");
      if(s.kind!=="issued")throw Error("session issue failed");
      assert.equal((await sessions.activate(owner,enrolled.deviceId,s.sessionId,s.nonce,
        s.binding,sign(null,connectorSessionProof(
          s.sessionId,s.challengeId,enrolled.deviceId,s.nonce,s.binding
        ),key.privateKey))).kind,"active");
      created[owner]={device:enrolled.deviceId,sessionId:s.sessionId};
    }
    await recoverLocalDevSessions(db);
    const states=(await db.query<{owner_sub:string;state:string}>(
      "SELECT owner_sub,state FROM connector_sessions ORDER BY owner_sub"
    )).rows;
    assert.deepEqual(states,[
      {owner_sub:"local-dev-owner",state:"closed"},
      {owner_sub:"other-owner",state:"active"}
    ]);
    assert.equal((await sessions.issue("local-dev-owner",created["local-dev-owner"]!.device)).kind,
      "issued","sandbox device can reconnect without waiting five-minute lease");
    assert.equal((await sessions.issue("other-owner",created["other-owner"]!.device)).kind,
      "unavailable","non-sandbox active session is not stolen");
    await recoverLocalDevSessions(db);
    assert.equal((await db.query<{state:string}>(
      "SELECT state FROM connector_sessions WHERE owner_sub='other-owner'"
    )).rows[0]?.state,"active");
  });
});