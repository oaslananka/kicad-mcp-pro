import assert from "node:assert/strict";
import {generateKeyPairSync,randomBytes,sign} from "node:crypto";
import {createServer} from "node:http";
import type {AddressInfo} from "node:net";
import {test} from "node:test";
import type {Pool} from "pg";
import {WebSocket} from "ws";
import {inIsolatedDatabase} from "./isolated-db.js";
import {PgPairingChallenges} from "../src/pairing-store.js";
import {deviceHandshakeProof,PgDeviceHandshakes} from "../src/device-handshake.js";
import {redemptionProof} from "../src/device-pairing.js";
import {connectorSessionProof,PgConnectorSessions} from "../src/connector-session.js";
import {PgConnectorReadGate} from "../src/connector-read-gate.js";
import {BoundConnectorConnections} from "../src/connector-transport-binding.js";
import {attachConnectorWebSocket} from "../src/connector-ws.js";

const url=process.env.TEST_DATABASE_URL;
const migrations=[
  "001_inventory.pgsql","002_client_grants.pgsql","005_token_cutoff.pgsql",
  "007_device_pairing.pgsql","008_device_credentials.pgsql",
  "009_device_handshake.pgsql","010_connector_sessions.pgsql"
];

function waitMessage(ws:WebSocket):Promise<Record<string,unknown>>{
  return new Promise((resolve,reject)=>{
    const timer=setTimeout(()=>{clean();reject(new Error("WEBSOCKET_TIMEOUT"));},8_000);
    function onMessage(data:WebSocket.RawData){
      clean();
      try{resolve(JSON.parse(data.toString()) as Record<string,unknown>);}
      catch{reject(new Error("INVALID_RESPONSE"));}
    }
    function onClose(){clean();reject(new Error("WEBSOCKET_CLOSED"));}
    function clean(){
      clearTimeout(timer);
      ws.off("message",onMessage);ws.off("close",onClose);
    }
    ws.once("message",onMessage);ws.once("close",onClose);
  });
}
function connect(uri:string,headers?:Record<string,string>):Promise<WebSocket>{
  return new Promise((resolve,reject)=>{
    const ws=new WebSocket(uri,{headers,perMessageDeflate:false});
    const timer=setTimeout(()=>{ws.terminate();reject(new Error("CONNECT_TIMEOUT"));},8_000);
    ws.once("open",()=>{clearTimeout(timer);resolve(ws);});
    ws.once("error",error=>{clearTimeout(timer);reject(error);});
  });
}
function waitClose(ws:WebSocket):Promise<number>{
  return new Promise((resolve,reject)=>{
    const timer=setTimeout(()=>{ws.terminate();reject(new Error("CLOSE_TIMEOUT"));},8_000);
    ws.once("close",code=>{clearTimeout(timer);resolve(code);});
  });
}
function send(ws:WebSocket,message:object):Promise<Record<string,unknown>>{
  const next=waitMessage(ws);
  ws.send(JSON.stringify(message));
  return next;
}
function field(obj:Record<string,unknown>,key:string):string{
  assert.equal(typeof obj[key],"string",key);
  return obj[key] as string;
}

async function startFixtureServer(
  db:Pool,operatorLocalOnce=false,nativeDrcOnce=false,inspectionOnce=false,
  boardCountsOnce=false
){
  const server=createServer((_req,res)=>{res.writeHead(404);res.end();});
  await new Promise<void>(resolve=>server.listen(0,"127.0.0.1",resolve));
  const port=(server.address() as AddressInfo).port;
  const attached=attachConnectorWebSocket(server,{
    publicOrigin:"http://127.0.0.1:"+port,
    sourceOf:()=>"127.0.0.1",
    proofs:new PgDeviceHandshakes(db),
    ...(operatorLocalOnce?{
      operatorLocalOnce:true,
      operatorNativeDrcOnce:nativeDrcOnce,
      operatorInspectionOnce:inspectionOnce,
      operatorBoardCountsOnce:boardCountsOnce
    }:
      {ownerConsent:{consume:async()=>true}}), // Synthetic, not human approval.
    connections:new BoundConnectorConnections(
      new PgConnectorSessions(db),new PgConnectorReadGate(db))
  });
  return {server,port,attached};
}

test("local one-shot cannot silently bypass a configured independent owner approval",
  {skip:!url,timeout:30_000},async()=>{
  await inIsolatedDatabase(url!,migrations,async db=>{
    const server=createServer((_req,res)=>{res.writeHead(404);res.end();});
    await new Promise<void>(resolve=>server.listen(0,"127.0.0.1",resolve));
    try{
      const port=(server.address() as AddressInfo).port;
      assert.throws(()=>attachConnectorWebSocket(server,{
        publicOrigin:"http://127.0.0.1:"+port,
        sourceOf:()=>"127.0.0.1",
        proofs:new PgDeviceHandshakes(db),
        connections:new BoundConnectorConnections(
          new PgConnectorSessions(db),new PgConnectorReadGate(db)),
        ownerConsent:{consume:async()=>false},
        operatorLocalOnce:true
      }),/Conflicting owner approval modes/);
    }finally{
      await new Promise<void>(resolve=>server.close(()=>resolve()));
    }
  });
});

test("outbound local WebSocket proves enrolled device identity then binds signed session",
  {skip:!url,timeout:60_000},async()=>{
  await inIsolatedDatabase(url!,migrations,async db=>{
    const owner="connector-user";
    const keys=generateKeyPairSync("ed25519");
    const publicKey=keys.publicKey.export({format:"der",type:"spki"}) as Buffer;
    const pair=new PgPairingChallenges(db,randomBytes(32));
    const pairing=await pair.issue("Loopback KiCad",publicKey);
    assert.equal(await pair.review(pairing.id,owner,pairing.userCode,"approve"),"approved");
    const enrolled=await pair.enroll(pairing.id,pairing.deviceCode,
      sign(null,redemptionProof(pairing.id,pairing.deviceCode),keys.privateKey));
    assert.equal(enrolled.kind,"enrolled");
    if(enrolled.kind!=="enrolled")return;
    const device=enrolled.deviceId;
    // Only a fixture. No public enablement endpoint exists.
    await db.query("UPDATE devices SET enabled=true WHERE id=$1",[device]);
    const {server,port,attached}=await startFixtureServer(db);
    let ws:WebSocket|undefined;
    try{
      // Browser-origin and query-string upgrade attempts must fail.
      await assert.rejects(connect("ws://127.0.0.1:"+port+"/api/v1/connector/ws",
        {Origin:"https://hostile.example"}),/403/);
      await assert.rejects(connect("ws://127.0.0.1:"+port+"/api/v1/connector/ws?token=leak"),
        /403/);
      ws=await connect("ws://127.0.0.1:"+port+"/api/v1/connector/ws");
      const hello=await send(ws,{kind:"device.hello",version:1,ownerSub:owner,deviceId:device});
      assert.equal(hello.kind,"device.challenge");
      const challengeId=field(hello,"challengeId"),nonce=field(hello,"nonce");
      assert.ok(!JSON.stringify((await db.query(
        "SELECT * FROM device_handshake_challenges WHERE id=$1",[challengeId])).rows[0]).includes(nonce));
      const first=sign(null,deviceHandshakeProof(challengeId,device,nonce),
        keys.privateKey).toString("base64url");
      const session=await send(ws,{kind:"device.proof",version:1,signature:first});
      assert.equal(session.kind,"connector.session_challenge");
      const id=field(session,"sessionId");
      const second=sign(null,connectorSessionProof(id,field(session,"challengeId"),
        device,field(session,"nonce"),field(session,"binding")),
        keys.privateKey).toString("base64url");
      const ready=await send(ws,{kind:"connector.session_proof",version:1,signature:second});
      assert.equal(ready.kind,"connector.ready");
      assert.equal((await db.query("SELECT state FROM connector_sessions WHERE id=$1",
        [id])).rows[0].state,"active");
      const close=waitClose(ws);
      ws.send(JSON.stringify({kind:"connector.execute",operation:"run_drc"}));
      assert.equal(await close,1008); // No native KiCad relay.
      // Closure should fence the persistent session as well.
      let state="active";
      for(let i=0;i<35;i++){
        state=(await db.query("SELECT state FROM connector_sessions WHERE id=$1",[id])).rows[0].state;
        if(state==="closed")break;
        await new Promise(resolve=>setTimeout(resolve,30));
      }
      assert.equal(state,"closed");
    }finally{
      ws?.terminate();
      await attached.close();
      await new Promise<void>(resolve=>server.close(()=>resolve()));
    }
  });
});

test("invalid device signature never starts an authenticated connector session",
  {skip:!url,timeout:60_000},async()=>{
  await inIsolatedDatabase(url!,migrations,async db=>{
    const owner="owner-invalid";
    const keys=generateKeyPairSync("ed25519");
    const der=keys.publicKey.export({format:"der",type:"spki"}) as Buffer;
    const pair=new PgPairingChallenges(db,randomBytes(32));
    const pending=await pair.issue("Bad signature test",der);
    await pair.review(pending.id,owner,pending.userCode,"approve");
    const enrolled=await pair.enroll(pending.id,pending.deviceCode,
      sign(null,redemptionProof(pending.id,pending.deviceCode),keys.privateKey));
    assert.equal(enrolled.kind,"enrolled");
    if(enrolled.kind!=="enrolled")return;
    await db.query("UPDATE devices SET enabled=true WHERE id=$1",[enrolled.deviceId]);
    const {server,port,attached}=await startFixtureServer(db);
    let ws:WebSocket|undefined;
    try{
      ws=await connect("ws://127.0.0.1:"+port+"/api/v1/connector/ws");
      const challenge=await send(ws,{kind:"device.hello",version:1,
        ownerSub:owner,deviceId:enrolled.deviceId});
      assert.equal(challenge.kind,"device.challenge");
      const close=waitClose(ws);
      const badKey=generateKeyPairSync("ed25519").privateKey;
      ws.send(JSON.stringify({kind:"device.proof",version:1,
        signature:sign(null,deviceHandshakeProof(field(challenge,"challengeId"),
          enrolled.deviceId,field(challenge,"nonce")),badKey).toString("base64url")}));
      assert.equal(await close,1008);
      assert.equal((await db.query("SELECT count(*)::integer AS count FROM connector_sessions"))
        .rows[0].count,0);
    }finally{
      ws?.terminate();
      await attached.close();
      await new Promise<void>(resolve=>server.close(()=>resolve()));
    }
  });
});

test("authenticated Cloud socket rejects revocation and expired reads after wall-clock rollback",
  {skip:!url,timeout:90_000},async()=>{
  for(const revocation of ["none","local_once","grant","device","token","clock_rollback"] as const){
    await inIsolatedDatabase(url!,migrations,async db=>{
      const owner="summary-owner",clientId="approved-client";
      const keys=generateKeyPairSync("ed25519");
      const der=keys.publicKey.export({format:"der",type:"spki"}) as Buffer;
      const pair=new PgPairingChallenges(db,randomBytes(32));
      const pairing=await pair.issue("Summary test",der);
      await pair.review(pairing.id,owner,pairing.userCode,"approve");
      const enrolled=await pair.enroll(pairing.id,pairing.deviceCode,
        sign(null,redemptionProof(pairing.id,pairing.deviceCode),keys.privateKey));
      assert.equal(enrolled.kind,"enrolled");
      if(enrolled.kind!=="enrolled")return;
      const device=enrolled.deviceId;
      const project="77777777-7777-4777-8777-777777777777";
      await db.query("UPDATE devices SET enabled=true WHERE id=$1",[device]);
      await db.query("INSERT INTO projects(id,owner_sub,device_id,alias,enabled,max_mode) "+
        "VALUES($1,$2,$3,'Fixture',true,'readonly')",[project,owner,device]);
      await db.query("INSERT INTO project_client_grants(project_id,owner_sub,client_id,enabled,max_mode) "+
        "VALUES($1,$2,$3,true,'readonly')",[project,owner,clientId]);
      const {server,port,attached}=await startFixtureServer(
        db,revocation==="local_once");
      let ws:WebSocket|undefined;
      const actualDateNow=Date.now;
      try{
        ws=await connect("ws://127.0.0.1:"+port+"/api/v1/connector/ws");
        const challenge=await send(ws,{kind:"device.hello",version:1,
          ownerSub:owner,deviceId:device});
        const signed=sign(null,deviceHandshakeProof(field(challenge,"challengeId"),
          device,field(challenge,"nonce")),keys.privateKey).toString("base64url");
        const session=await send(ws,{kind:"device.proof",version:1,signature:signed});
        const signature=sign(null,connectorSessionProof(field(session,"sessionId"),
          field(session,"challengeId"),device,field(session,"nonce"),
          field(session,"binding")),keys.privateKey).toString("base64url");
        const ready=await send(ws,{kind:"connector.session_proof",version:1,signature});
        assert.equal(ready.kind,"connector.ready");
        const oauth={ownerSub:owner,clientId,accessTokenIssuedAtSeconds:Math.floor(Date.now()/1000)};
        // First publish a precise server-issued intent for the human
        // approval ceremony. Nothing is sent to the device yet.
        let prepared=attached.prepareOwnerSummary(oauth,device,project);
        assert.ok(prepared,"Ready device can reserve a one-use owner intent");
        assert.equal(prepared.operation,"project_summary");
        assert.equal(prepared.ownerSub,owner);
        assert.equal(prepared.clientId,clientId);
        assert.equal(prepared.deviceId,device);
        assert.equal(prepared.projectId,project);
        assert.equal(attached.prepareOwnerSummary(oauth,device,project),null,
          "Only one outstanding intent per socket is allowed");
        assert.equal(await attached.requestSummary(oauth,device,project),null,
          "Legacy dispatch cannot bypass an unapproved reservation");
        assert.equal(await attached.requestSummary(oauth,device,project,
          {...prepared}),null,"A copied intent is not an authorization token");
        if(revocation==="none"){
          // An exact legitimate reservation cannot be rebound to another
          // OAuth client; even the original reference is then burned.
          assert.equal(await attached.requestSummary(
            {...oauth,clientId:"untrusted-other-client"},device,project,prepared),
            null,"Wrong OAuth client must not consume a signed owner intent");
          assert.equal(await attached.requestSummary(oauth,device,project,prepared),
            null,"Wrong-client attempt must permanently burn that intent");
          const next=attached.prepareOwnerSummary(oauth,device,project);
          assert.ok(next,"A fresh explicit owner decision needs a new intent");
          assert.notEqual(next.requestId,prepared.requestId);
          prepared=next;
        }
        const outbound=waitMessage(ws);
        const pending=attached.requestSummary(oauth,device,project,prepared);
        const frame=await outbound;
        assert.equal(frame.kind,"connector.authorized_read");
        assert.equal(frame.sequence,1);
        const request=frame.request as Record<string,unknown>;
        assert.equal(request.kind,"connector.read_request");
        assert.equal(request.operation,"project_summary");
        assert.equal(request.projectId,project);
        assert.equal(request.requestId,prepared.requestId,
          "WSS request must match exact reviewed owner intent");
        assert.equal(await attached.requestSummary(oauth,device,project,prepared),
          null,"Prepared owner intent is single-use");
        if(revocation==="grant"){
          await db.query("UPDATE project_client_grants SET enabled=false WHERE project_id=$1",
            [project]);
        }else if(revocation==="device"){
          assert.equal(await pair.revokeDevice(owner,device),true);
          assert.equal((await db.query<{state:string}>(
            "SELECT state FROM connector_sessions WHERE device_id=$1",[device])
          ).rows[0].state,"revoked");
        }else if(revocation==="token"){
          await db.query("INSERT INTO client_token_cutoffs(owner_sub,client_id,revoked_at) "+
            "VALUES($1,$2,clock_timestamp())",[owner,clientId]);
        }else if(revocation==="clock_rollback"){
          // The wire deadline is 8 s. A host wall-clock rollback must not
          // revive a read that took longer than the operator's grant.
          await new Promise(resolve=>setTimeout(resolve,8_200));
          Date.now=()=>actualDateNow()-30_000;
        }
        const reply={kind:"connector.local_read_preview",version:1,
          requestId:request.requestId,projectId:project,operation:"project_summary",
          files:{projectPresent:true,boardPresent:false,schematicPresent:true}};
        const success=revocation==="none"||revocation==="local_once";
        const ack=success ? waitMessage(ws) : null;
        const close=success ? null : waitClose(ws);
        ws.send(JSON.stringify({kind:"connector.read_result",version:1,
          sequence:1,result:reply}));
        const result=await pending;
        if(!success){
          assert.equal(result,null,"Must not return private project metadata after "+revocation);
          assert.equal(await close,1008,"Must close the revoked socket without an ACK");
        }else{
          assert.deepEqual(result,reply);
          const receipt=await ack!;
          assert.equal(receipt.kind,"connector.read_ack");
          assert.equal(receipt.requestId,request.requestId);
        }
      }finally{
        Date.now=actualDateNow;
        ws?.terminate();
        await attached.close();
        await new Promise<void>(resolve=>server.close(()=>resolve()));
      }
    });
  }
});

// Local integration-only: real cryptographic WSS challenges, isolated SQL
// grant state, and strict native DRC reply framing. Not an owner/WebAuthn UV.
test("signed one-shot WSS admits only explicit native DRC count results",
  {skip:!url,timeout:70_000},async()=>{
  for(const behavior of ["allowed","wrong_operation","revoked","flag_off"] as const){
    await inIsolatedDatabase(url!,migrations,async db=>{
      const owner="native-drc-owner",clientId="native-drc-client";
      const keys=generateKeyPairSync("ed25519");
      const der=keys.publicKey.export({format:"der",type:"spki"}) as Buffer;
      const pair=new PgPairingChallenges(db,randomBytes(32));
      const challenge=await pair.issue("Test board",der);
      assert.equal(await pair.review(challenge.id,owner,challenge.userCode,"approve"),"approved");
      const enrolled=await pair.enroll(challenge.id,challenge.deviceCode,
        sign(null,redemptionProof(challenge.id,challenge.deviceCode),keys.privateKey));
      assert.equal(enrolled.kind,"enrolled");
      if(enrolled.kind!=="enrolled")return;
      const device=enrolled.deviceId;
      const project="77777777-7777-4777-8777-777777777777";
      await db.query("UPDATE devices SET enabled=true WHERE id=$1",[device]);
      await db.query("INSERT INTO projects(id,owner_sub,device_id,alias,enabled,max_mode) "+
        "VALUES($1,$2,$3,'Safe DRC',true,'readonly')",[project,owner,device]);
      await db.query("INSERT INTO project_client_grants(project_id,owner_sub,client_id,enabled,max_mode) "+
        "VALUES($1,$2,$3,true,'readonly')",[project,owner,clientId]);
      const {server,port,attached}=await startFixtureServer(db,true,behavior!=="flag_off");
      let ws:WebSocket|undefined;
      try{
        ws=await connect("ws://127.0.0.1:"+port+"/api/v1/connector/ws");
        const hello=await send(ws,{
          kind:"device.hello",version:1,ownerSub:owner,deviceId:device
        });
        const deviceSignature=sign(null,deviceHandshakeProof(
          field(hello,"challengeId"),device,field(hello,"nonce")),
        keys.privateKey).toString("base64url");
        const session=await send(ws,{
          kind:"device.proof",version:1,signature:deviceSignature
        });
        const sessionSignature=sign(null,connectorSessionProof(
          field(session,"sessionId"),field(session,"challengeId"),device,
          field(session,"nonce"),field(session,"binding")),
        keys.privateKey).toString("base64url");
        const ready=await send(ws,{
          kind:"connector.session_proof",version:1,signature:sessionSignature
        });
        assert.equal(ready.kind,"connector.ready");
        const oauth={ownerSub:owner,clientId,
          accessTokenIssuedAtSeconds:Math.floor(Date.now()/1000)};
        const pendingIntent=attached.prepareOwnerDrc(oauth,device,project);
        if(behavior==="flag_off"){
          assert.equal(pendingIntent,null,"A normal one-shot session cannot invoke native DRC");
          return;
        }
        assert.ok(pendingIntent);
        assert.equal(pendingIntent.operation,"run_drc");
        assert.equal(attached.prepareOwnerSummary(oauth,device,project),null,
          "A signed WSS session reserves only one operation");
        const outbound=waitMessage(ws);
        const promise=attached.requestDrc(oauth,device,project,pendingIntent);
        const frame=await outbound;
        assert.equal(frame.kind,"connector.authorized_read");
        const request=frame.request as Record<string,unknown>;
        assert.equal(request.operation,"run_drc");
        assert.equal(request.projectId,project);
        assert.equal(request.requestId,pendingIntent.requestId);
        assert.equal(await attached.requestDrc(oauth,device,project,pendingIntent),
          null,"An issued intent is single-use");
        if(behavior==="revoked")
          await db.query("UPDATE project_client_grants SET enabled=false "+
            "WHERE project_id=$1",[project]);
        const reply=behavior==="wrong_operation"?
          {kind:"connector.local_read_preview",version:1,
            requestId:request.requestId,projectId:project,
            operation:"project_summary",
            files:{projectPresent:true,boardPresent:true,schematicPresent:true}}:
          {kind:"connector.local_drc_preview",version:1,
            requestId:request.requestId,projectId:project,operation:"run_drc",
            counts:{violations:1,unconnectedItems:0}};
        const ack=behavior==="allowed"?waitMessage(ws):null;
        ws.send(JSON.stringify({
          kind:"connector.read_result",version:1,sequence:1,result:reply
        }));
        const result=await promise;
        if(behavior==="allowed"){
          assert.deepEqual(result,reply);
          const confirmation=await ack!;
          assert.equal(confirmation.kind,"connector.read_ack");
          assert.equal(confirmation.requestId,request.requestId);
        }else{
          assert.equal(result,null,"No counts after revocation or operation confusion");
        }
      }finally{
        ws?.terminate();
        await attached.close();
        await new Promise<void>(resolve=>server.close(()=>resolve()));
      }
    });
  }
});

test("manual WSS project inspection uses exact grant and discards invalid typed outputs",
  {skip:!url,timeout:90_000},async()=>{
  for(const operation of ["inspection","board_counts"] as const){
  for(const behavior of ["allowed","wrong_result","revoked","flag_off"] as const){
    await inIsolatedDatabase(url!,migrations,async db=>{
      const owner="inspect-owner",clientId="inspect-client";
      const keys=generateKeyPairSync("ed25519");
      const der=keys.publicKey.export({format:"der",type:"spki"}) as Buffer;
      const pair=new PgPairingChallenges(db,randomBytes(32));
      const challenge=await pair.issue("Inspection project",der);
      assert.equal(await pair.review(challenge.id,owner,challenge.userCode,"approve"),"approved");
      const enrolled=await pair.enroll(challenge.id,challenge.deviceCode,
        sign(null,redemptionProof(challenge.id,challenge.deviceCode),keys.privateKey));
      assert.equal(enrolled.kind,"enrolled");
      if(enrolled.kind!=="enrolled")return;
      const device=enrolled.deviceId,project="77777777-7777-4777-8777-777777777777";
      await db.query("UPDATE devices SET enabled=true WHERE id=$1",[device]);
      await db.query("INSERT INTO projects(id,owner_sub,device_id,alias,enabled,max_mode) "+
        "VALUES($1,$2,$3,'Inspection',true,'readonly')",[project,owner,device]);
      await db.query("INSERT INTO project_client_grants(project_id,owner_sub,client_id,enabled,max_mode) "+
        "VALUES($1,$2,$3,true,'readonly')",[project,owner,clientId]);
      const {server,port,attached}=await startFixtureServer(
        db,true,false,operation==="inspection"&&behavior!=="flag_off",
        operation==="board_counts"&&behavior!=="flag_off");
      let ws:WebSocket|undefined;
      try{
        ws=await connect("ws://127.0.0.1:"+port+"/api/v1/connector/ws");
        const hello=await send(ws,{kind:"device.hello",version:1,ownerSub:owner,deviceId:device});
        const signed=sign(null,deviceHandshakeProof(
          field(hello,"challengeId"),device,field(hello,"nonce")),keys.privateKey
        ).toString("base64url");
        const session=await send(ws,{
          kind:"device.proof",version:1,signature:signed
        });
        const proof=sign(null,connectorSessionProof(
          field(session,"sessionId"),field(session,"challengeId"),device,
          field(session,"nonce"),field(session,"binding")),keys.privateKey
        ).toString("base64url");
        const ready=await send(ws,{
          kind:"connector.session_proof",version:1,signature:proof
        });
        assert.equal(ready.kind,"connector.ready");
        const oauth={ownerSub:owner,clientId,
          accessTokenIssuedAtSeconds:Math.floor(Date.now()/1000)};
        // A granted engine-status operation cannot authorize PCB inspection.
        assert.equal(
          operation==="inspection"?attached.prepareOwnerBoardCounts(oauth,device,project)
            :attached.prepareOwnerInspection(oauth,device,project),
          null
        );
        const intent=operation==="inspection"?
          attached.prepareOwnerInspection(oauth,device,project):
          attached.prepareOwnerBoardCounts(oauth,device,project);
        if(behavior==="flag_off"){
          assert.equal(intent,null,"Old Cloud grants cannot activate a new operation");
          return;
        }
        assert.ok(intent);
        assert.equal(intent.operation,operation==="inspection"?
          "project_worker_inspection":"project_board_counts");
        const outbound=waitMessage(ws);
        const pending=operation==="inspection"?
          attached.requestInspection(oauth,device,project,
            intent as NonNullable<ReturnType<typeof attached.prepareOwnerInspection>>):
          attached.requestBoardCounts(oauth,device,project,
            intent as NonNullable<ReturnType<typeof attached.prepareOwnerBoardCounts>>);
        const sent=await outbound;
        assert.equal(sent.kind,"connector.authorized_read");
        const request=sent.request as Record<string,unknown>;
        assert.equal(request.operation,operation==="inspection"?
          "project_worker_inspection":"project_board_counts");
        assert.equal(request.projectId,project);
        assert.equal(operation==="inspection"?
          await attached.requestInspection(oauth,device,project,
            intent as NonNullable<ReturnType<typeof attached.prepareOwnerInspection>>):
          await attached.requestBoardCounts(oauth,device,project,
            intent as NonNullable<ReturnType<typeof attached.prepareOwnerBoardCounts>>),null);
        if(behavior==="revoked")
          await db.query("UPDATE project_client_grants SET enabled=false WHERE project_id=$1",
            [project]);
        const good={
          kind:"connector.local_worker_inspection",version:1,
          requestId:request.requestId,projectId:project,
          operation:"project_worker_inspection",
          status:{engineVersion:"4.6.1",cliAvailable:true,ipcAvailable:false,
          capabilities:{fileBackedDrc:true,fileBackedErc:true,
            livePcbRead:false,liveSchematicRead:false}}
        };
        const boardResult={
          kind:"connector.local_board_counts",version:1,
          requestId:request.requestId,projectId:project,
          operation:"project_board_counts",source:"file-backed",
          counts:{tracks:1,vias:2,footprints:3,zones:4,nets:5,shapes:6}
        };
        const goodResult=operation==="inspection"?good:boardResult;
        const result=behavior==="wrong_result"?
          operation==="inspection"?
            {...good,status:{...good.status,capabilities:{
                ...good.status.capabilities,localPath:"/private/board"}}}:
            {...boardResult,counts:{...boardResult.counts,
              localPath:"/private/board"}}:goodResult;
        const ack=behavior==="allowed"?waitMessage(ws):null;
        ws.send(JSON.stringify({
          kind:"connector.read_result",version:1,sequence:1,result
        }));
        const response=await pending;
        if(behavior==="allowed"){
          assert.deepEqual(response,goodResult);
          const confirmed=await ack!;
          assert.equal(confirmed.kind,"connector.read_ack");
          assert.equal(confirmed.requestId,request.requestId);
        }else assert.equal(response,null);
      }finally{
        ws?.terminate();
        await attached.close();
        await new Promise<void>(resolve=>server.close(()=>resolve()));
      }
    });
  }
  }
});
