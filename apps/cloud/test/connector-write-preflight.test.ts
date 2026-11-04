import assert from "node:assert/strict";
import {generateKeyPairSync,randomBytes,randomUUID,sign} from "node:crypto";
import {test} from "node:test";
import {inIsolatedDatabase} from "./isolated-db.js";
import {PgPairingChallenges} from "../src/pairing-store.js";
import {redemptionProof} from "../src/device-pairing.js";
import {PgConnectorSessions,connectorSessionProof} from "../src/connector-session.js";
import {PgConnectorWritePreflight} from "../src/connector-write-preflight.js";
import type {Actor} from "../src/auth.js";
import type {TrustedConnectorContext} from "../src/connector-read-gate.js";

const url=process.env.TEST_DATABASE_URL;
const migrations=[
  "001_inventory.pgsql","002_client_grants.pgsql","005_token_cutoff.pgsql",
  "007_device_pairing.pgsql","008_device_credentials.pgsql",
  "009_device_handshake.pgsql","010_connector_sessions.pgsql"
];

test("remote write preflight fails closed until owner, project, client, scopes and live connector all opt in",
  {skip:!url},async()=>{
  await inIsolatedDatabase(url!,migrations,async db=>{
    const owner="owner-write-preflight",clientId="editor-ai";
    const keys=generateKeyPairSync("ed25519");
    const pairing=new PgPairingChallenges(db,randomBytes(32));
    const pending=await pairing.issue("Disposable write preflight",
      keys.publicKey.export({format:"der",type:"spki"}) as Buffer);
    assert.equal(await pairing.review(pending.id,owner,pending.userCode,"approve"),"approved");
    const enrolled=await pairing.enroll(pending.id,pending.deviceCode,
      sign(null,redemptionProof(pending.id,pending.deviceCode),keys.privateKey));
    assert.equal(enrolled.kind,"enrolled");
    if(enrolled.kind!=="enrolled")return;
    const deviceId=enrolled.deviceId;
    await db.query("UPDATE devices SET enabled=true WHERE id=$1",[deviceId]);
    const sessionStore=new PgConnectorSessions(db);
    const challenge=await sessionStore.issue(owner,deviceId);
    assert.equal(challenge.kind,"issued");
    if(challenge.kind!=="issued")return;
    const signature=sign(null,connectorSessionProof(challenge.sessionId,
      challenge.challengeId,deviceId,challenge.nonce,challenge.binding),keys.privateKey);
    assert.equal((await sessionStore.activate(owner,deviceId,challenge.sessionId,
      challenge.nonce,challenge.binding,signature)).kind,"active");
    const projectId=randomUUID(),foreignProjectId=randomUUID();
    await db.query("INSERT INTO projects(id,owner_sub,device_id,alias,enabled) "+
      "VALUES($1,$3,$4,'Board A',true),($2,$3,$4,'Board B',true)",
      [projectId,foreignProjectId,owner,deviceId]);
    const scope=new Set(["projects:read","projects:write"]);
    const actor:Actor={sub:owner,clientId,scopes:scope,issuedAt:Math.floor(Date.now()/1000)-30};
    const connection:TrustedConnectorContext={
      deviceId,sessionId:challenge.sessionId,connectionBinding:challenge.binding
    };
    const gate=new PgConnectorWritePreflight(db);
    const check=(identity:Actor=actor,conn:TrustedConnectorContext=connection,project:string=projectId)=>
      gate.checkCurrentPolicy(identity,conn,project);
    // A fresh paired device and an OAuth write token never create implicit permissions.
    assert.equal(await check(),false);
    await db.query("INSERT INTO project_client_grants "+
      "(project_id,owner_sub,client_id,enabled,max_mode) VALUES($1,$2,$3,true,'readonly')",
      [projectId,owner,clientId]);
    assert.equal(await check(),false);
    await db.query("UPDATE projects SET max_mode='write' WHERE id=$1",[projectId]);
    assert.equal(await check(),false);
    await db.query("UPDATE project_client_grants SET max_mode='write' WHERE project_id=$1",[projectId]);
    assert.equal(await check(),true);
    assert.equal(await check({...actor,scopes:new Set(["projects:read"])}),false);
    assert.equal(await check({...actor,scopes:new Set(["projects:write"])}),false);
    assert.equal(await check({...actor,clientId:"ungranted-ai"}),false);
    assert.equal(await check({...actor,sub:"another-owner"}),false);
    assert.equal(await check(actor,connection,foreignProjectId),false);
    assert.equal(await check(actor,connection,"../../etc/passwd"),false);
    assert.equal(await check({...actor,issuedAt:Math.floor(Date.now()/1000)+120}),false);
    assert.equal(await check(actor,{...connection,connectionBinding:randomBytes(32).toString("base64url")}),false);
    assert.equal(await check(actor,{...connection,sessionId:randomUUID()}),false);
    await db.query("UPDATE project_client_grants SET enabled=false WHERE project_id=$1",[projectId]);
    assert.equal(await check(),false);
    await db.query("UPDATE project_client_grants SET enabled=true WHERE project_id=$1",[projectId]);
    await db.query("UPDATE projects SET enabled=false WHERE id=$1",[projectId]);
    assert.equal(await check(),false);
    await db.query("UPDATE projects SET enabled=true WHERE id=$1",[projectId]);
    await db.query("UPDATE projects SET max_mode='readonly' WHERE id=$1",[projectId]);
    assert.equal(await check(),false);
    await db.query("UPDATE projects SET max_mode='write' WHERE id=$1",[projectId]);
    assert.equal(await check(),true);
    await db.query("INSERT INTO client_token_cutoffs(owner_sub,client_id,revoked_at) "+
      "VALUES($1,$2,clock_timestamp()-interval '15 seconds')",[owner,clientId]);
    assert.equal(await check(),false,"revoked old token cannot edit despite an existing grant");
    const refreshed={...actor,issuedAt:Math.floor(Date.now()/1000)-2};
    assert.equal(await check(refreshed),true);
    await db.query("UPDATE connector_sessions SET state='expired' WHERE id=$1",
      [challenge.sessionId]);
    assert.equal(await check(refreshed),false);
    await db.query("UPDATE connector_sessions SET state='active' WHERE id=$1",
      [challenge.sessionId]);
    assert.equal(await check(refreshed),true);
    await db.query("UPDATE connector_sessions SET "+
      "created_at=created_at-interval '6 minutes',"+
      "expires_at=expires_at-interval '6 minutes' WHERE id=$1",[challenge.sessionId]);
    assert.equal(await check(refreshed),false);
    await db.query("UPDATE connector_sessions SET "+
      "created_at=created_at+interval '6 minutes',"+
      "expires_at=expires_at+interval '6 minutes' WHERE id=$1",[challenge.sessionId]);
    assert.equal(await check(refreshed),true);
    assert.equal(await pairing.revokeDevice(owner,deviceId),true);
    assert.equal(await check(refreshed),false,"revoked device always blocks writes");
  });
});
