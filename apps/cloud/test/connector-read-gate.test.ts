import assert from "node:assert/strict";
import {generateKeyPairSync,randomBytes,randomUUID,sign} from "node:crypto";
import {test} from "node:test";
import {inIsolatedDatabase} from "./isolated-db.js";
import {PgPairingChallenges} from "../src/pairing-store.js";
import {redemptionProof} from "../src/device-pairing.js";
import {PgConnectorSessions,connectorSessionProof} from "../src/connector-session.js";
import {PgConnectorReadGate,signedReadProof,
  type TrustedOAuthReadIdentity,type TrustedConnectorContext}
  from "../src/connector-read-gate.js";

const url=process.env.TEST_DATABASE_URL;
test("signed readonly envelopes require current owner, client, session and project policy",
  {skip:!url},async()=>{
  await inIsolatedDatabase(url!,[
    "001_inventory.pgsql","002_client_grants.pgsql","005_token_cutoff.pgsql",
    "007_device_pairing.pgsql","008_device_credentials.pgsql",
    "009_device_handshake.pgsql","010_connector_sessions.pgsql"
  ],async db=>{
    const owner="owner-1", client="approved-ai-client";
    const keys=generateKeyPairSync("ed25519");
    const publicDer=keys.publicKey.export({format:"der",type:"spki"}) as Buffer;
    const pair=new PgPairingChallenges(db,randomBytes(32));
    const first=await pair.issue("Read-only Lab",publicDer);
    assert.equal(await pair.review(first.id,owner,first.userCode,"approve"),"approved");
    const proof=sign(null,redemptionProof(first.id,first.deviceCode),keys.privateKey);
    const enrolled=await pair.enroll(first.id,first.deviceCode,proof);
    assert.equal(enrolled.kind,"enrolled");
    if(enrolled.kind!=="enrolled")return;
    const device=enrolled.deviceId;
    await db.query("UPDATE devices SET enabled=true WHERE id=$1",[device]);
    const sessionStore=new PgConnectorSessions(db);
    const issued=await sessionStore.issue(owner,device);
    assert.equal(issued.kind,"issued");
    if(issued.kind!=="issued")return;
    const sessionSignature=sign(null,connectorSessionProof(issued.sessionId,
      issued.challengeId,device,issued.nonce,issued.binding),keys.privateKey);
    assert.equal((await sessionStore.activate(owner,device,issued.sessionId,
      issued.nonce,issued.binding,sessionSignature)).kind,"active");
    const project=randomUUID(),otherProject=randomUUID();
    await db.query("INSERT INTO projects(id,device_id,owner_sub,alias,enabled) "+
      "VALUES($1,$3,$4,'Demo PCB',true),($2,$3,$4,'Denied PCB',false)",
      [project,otherProject,device,owner]);
    const gateA=new PgConnectorReadGate(db),gateB=new PgConnectorReadGate(db);
    const connection:TrustedConnectorContext={
      deviceId:device,sessionId:issued.sessionId,connectionBinding:issued.binding
    };
    const oauth:TrustedOAuthReadIdentity={
      ownerSub:owner,clientId:client,
      accessTokenIssuedAtSeconds:Math.floor(Date.now()/1000)-30
    };
    const packet=(id:string,operation="project_summary",extra:object={})=>Buffer.from(
      JSON.stringify({kind:"connector.read_request",version:1,requestId:randomUUID(),
        deviceId:device,projectId:id,operation,deadlineUnixMs:Date.now()+27_000,...extra}),"utf8");
    function attempt(sequence:number,raw:Buffer,identity=oauth,conn=connection,
      key=keys.privateKey){
      return {
        run:gateA.verifySignedRead(identity,conn,sequence,raw,
          sign(null,signedReadProof(identity,conn,sequence,raw),key))
      };
    }
    const initial=packet(project);
    assert.equal((await attempt(1,initial).run).kind,"unavailable"); // default deny
    await db.query("INSERT INTO project_client_grants "+
      "(project_id,owner_sub,client_id,enabled,max_mode) VALUES($1,$2,$3,true,'readonly')",
      [project,owner,client]);
    const forged=generateKeyPairSync("ed25519");
    assert.equal((await attempt(1,packet(project),oauth,connection,forged.privateKey).run).kind,"unavailable");
    assert.equal((await attempt(1,packet(project),{...oauth,clientId:"other-client"}).run).kind,"unavailable");
    assert.equal((await attempt(1,packet(otherProject)).run).kind,"unavailable");
    assert.equal((await attempt(1,packet(project,"shell.execute")).run).kind,"unavailable");
    // A valid signature plus owner/client/device/project grant is never
    // permission to execute DRC or ERC on the local KiCad engine.
    assert.equal((await attempt(1,packet(project,"run_drc")).run).kind,"unavailable");
    assert.equal((await attempt(1,packet(project,"run_erc")).run).kind,"unavailable");
    assert.equal((await attempt(1,packet(project,"run_drc",{localPath:"/tmp/design.kicad_pcb"})).run).kind,"unavailable");
    assert.equal((await attempt(1,packet(project,"run_drc",{deviceId:randomUUID()})).run).kind,"unavailable");
    assert.equal((await attempt(1,packet(project,"run_drc",{deadlineUnixMs:Date.now()+90_000})).run).kind,"unavailable");
    const wrongBinding={...connection,connectionBinding:randomBytes(32).toString("base64url")};
    assert.equal((await attempt(1,packet(project),oauth,wrongBinding).run).kind,"unavailable");
    assert.equal((await attempt(1,packet(project),{...oauth,ownerSub:"foreign-owner"}).run).kind,"unavailable");
    const afterBad=(await db.query("SELECT last_sequence FROM connector_sessions WHERE id=$1",
      [issued.sessionId])).rows[0].last_sequence;
    assert.equal(Number(afterBad),0);

    const payload=packet(project);
    const legitimate=sign(null,signedReadProof(oauth,connection,1,payload),keys.privateKey);
    const duplicates=await Promise.all([
      gateA.verifySignedRead(oauth,connection,1,payload,legitimate),
      gateB.verifySignedRead(oauth,connection,1,payload,legitimate)
    ]);
    assert.deepEqual(duplicates.map(r=>r.kind).sort(),["accepted","unavailable"]);
    assert.equal(duplicates.find(r=>r.kind==="accepted")?.kind,"accepted");
    assert.equal((await gateA.verifySignedRead(oauth,connection,1,payload,legitimate)).kind,"unavailable");

    // Per-client token revocation cuts off old JWTs even when a grant survives.
    await db.query("INSERT INTO client_token_cutoffs(owner_sub,client_id,revoked_at) "+
      "VALUES($1,$2,clock_timestamp()-interval '15 seconds')",[owner,client]);
    assert.equal((await attempt(2,packet(project)).run).kind,"unavailable");
    const fresh={...oauth,accessTokenIssuedAtSeconds:Math.floor(Date.now()/1000)-3};
    const valid2=packet(project,"project_summary");
    assert.equal((await attempt(2,valid2,fresh).run).kind,"accepted");
    await db.query("UPDATE project_client_grants SET enabled=false WHERE project_id=$1",[project]);
    assert.equal((await attempt(3,packet(project),fresh).run).kind,"unavailable");
    await db.query("UPDATE project_client_grants SET enabled=true WHERE project_id=$1",[project]);
    await db.query("UPDATE projects SET enabled=false WHERE id=$1",[project]);
    assert.equal((await attempt(3,packet(project),fresh).run).kind,"unavailable");
    await db.query("UPDATE projects SET enabled=true WHERE id=$1",[project]);
    // Re-enabling the project does not broaden the operation whitelist.
    assert.equal((await attempt(3,packet(project,"run_drc"),fresh).run).kind,"unavailable");
    assert.equal((await attempt(3,packet(project,"run_erc"),fresh).run).kind,"unavailable");
    assert.equal((await attempt(3,packet(project,"project_summary"),fresh).run).kind,"accepted");

    // Old sequence cannot become valid after a client or project re-grant.
    assert.equal((await attempt(2,packet(project),fresh).run).kind,"unavailable");
    assert.equal(await pair.revokeDevice(owner,device),true);
    assert.equal((await attempt(4,packet(project),fresh).run).kind,"unavailable");
    assert.equal((await db.query("SELECT state FROM connector_sessions WHERE id=$1",
      [issued.sessionId])).rows[0].state,"revoked");
  });
});
