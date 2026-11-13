import assert from "node:assert/strict";
import {createServer} from "node:http";
import {randomBytes,randomUUID} from "node:crypto";
import type {AddressInfo} from "node:net";
import {test} from "node:test";
import {WebSocket} from "ws";
import {BoundConnectorConnections} from "../src/connector-transport-binding.js";
import {attachConnectorWebSocket} from "../src/connector-ws.js";
import type {PgDeviceHandshakes} from "../src/device-handshake.js";
import type {PgConnectorSessions} from "../src/connector-session.js";
import type {PgConnectorReadGate} from "../src/connector-read-gate.js";

const owner="prod-owner-account";
const deviceId=randomUUID();
const rootListing={folderId:"root",name:"KiCad Projects",parentId:null,
  project:false,more:false,
  folders:[{id:"child-token",name:"Motor Board",project:true}]};

/** In-memory device proof port: verifies the handshake order, not crypto. */
const proofs={
  issue:async(o:string,d:string)=>{
    if(o!==owner&&o!=="local-dev-owner")return {kind:"unavailable"};
    return {kind:"issued",challengeId:"chal-"+d,deviceId:d,nonce:"n",
      expiresAtMs:Date.now()+60_000};
  },
  verify:async(o:string,d:string)=>{
    if(o!==owner&&o!=="local-dev-owner")return {kind:"unavailable"};
    return {kind:"verified",deviceId:d};
  },
  cancel:async()=>{}
} as unknown as PgDeviceHandshakes;

/** In-memory signed session store with the same issue/activate/close order. */
const sessions={
  issue:async(o:string,d:string)=>{
    if(o!==owner&&o!=="local-dev-owner")return {kind:"unavailable"};
    return {kind:"issued",sessionId:"sess-"+d,challengeId:"schal-"+d,
      nonce:"sn",binding:"bind-"+d,expiresAtMs:Date.now()+300_000};
  },
  activate:async()=>({kind:"active" as const}),
  close:async()=>{}
} as unknown as PgConnectorSessions;

const admission={
  verifySignedRead:async()=>({kind:"unavailable" as const})
} as unknown as PgConnectorReadGate;

function attach(mode:"production"|"local-dev"){
  const server=createServer((_req,res)=>{res.writeHead(404);res.end();});
  return new Promise<{close:()=>Promise<void>;port:number;attached:
    ReturnType<typeof attachConnectorWebSocket>}>(resolve=>{
    server.listen(0,"127.0.0.1",()=>{
      const port=(server.address() as AddressInfo).port;
      const attached=attachConnectorWebSocket(server,{
        publicOrigin:"http://127.0.0.1:"+port,
        sourceOf:()=>"127.0.0.1",
        proofs,
        connections:new BoundConnectorConnections(sessions,admission),
        ...(mode==="production"?{productionFolderBrowse:true}
          :{localDevFolderBrowse:true})
      });
      resolve({attached,port,close:async()=>{
        await attached.close();
        await new Promise<void>(r=>server.close(()=>r()));
      }});
    });
  });
}

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
      clearTimeout(timer);ws.off("message",onMessage);ws.off("close",onClose);
    }
    ws.once("message",onMessage);ws.once("close",onClose);
  });
}

function connect(port:number):Promise<WebSocket>{
  return new Promise((resolve,reject)=>{
    const ws=new WebSocket("ws://127.0.0.1:"+port+"/api/v1/connector/ws",
      {perMessageDeflate:false});
    const timer=setTimeout(()=>{ws.terminate();reject(new Error("CONNECT_TIMEOUT"));},8_000);
    ws.once("open",()=>{clearTimeout(timer);resolve(ws);});
    ws.once("error",error=>{clearTimeout(timer);reject(error);});
  });
}

/** Drive the real three-step signed handshake order against the local WSS. */
async function readySession(port:number,ownerSub:string):Promise<WebSocket>{
  const ws=await connect(port);
  await new Promise<void>((resolve,reject)=>{
    const next=waitMessage(ws);
    ws.send(JSON.stringify({kind:"device.hello",version:1,
      ownerSub:ownerSub,deviceId}));
    next.then(message=>{
      assert.equal(message.kind,"device.challenge");
      ws.send(JSON.stringify({kind:"device.proof",version:1,
        signature:randomBytes(64).toString("base64url")}));
      resolve();
    },reject);
  });
  const sessionChallenge=await waitMessage(ws);
  assert.equal(sessionChallenge.kind,"connector.session_challenge");
  const sessionNext=waitMessage(ws);
  ws.send(JSON.stringify({kind:"connector.session_proof",version:1,
    signature:randomBytes(64).toString("base64url")}));
  const ready=await sessionNext;
  assert.equal(ready.kind,"connector.ready");
  return ws;
}

test("folder browse modes are mutually exclusive",async()=>{
  const server=createServer((_req,res)=>{res.writeHead(404);res.end();});
  await new Promise<void>(resolve=>server.listen(0,"127.0.0.1",resolve));
  try{
    const port=(server.address() as AddressInfo).port;
    assert.throws(()=>attachConnectorWebSocket(server,{
      publicOrigin:"http://127.0.0.1:"+port,
      sourceOf:()=>"127.0.0.1",
      proofs,
      connections:new BoundConnectorConnections(sessions,admission),
      localDevFolderBrowse:true,
      productionFolderBrowse:true
    }),/Conflicting folder browse modes/);
  }finally{
    await new Promise<void>(resolve=>server.close(()=>resolve()));
  }
});

test("production owner browses real signed device folders without local-dev owner",async()=>{
  const wss=await attach("production");
  let ws:WebSocket|undefined;
  try{
    ws=await readySession(wss.port,owner);
    // Offline / unowned device can never be asked to browse.
    assert.equal(await wss.attached.localFolders.listFolder(owner,randomUUID(),"root"),null);
    assert.equal(await wss.attached.localFolders.listFolder("someone-else",deviceId,"root"),null);
    const framePromise=waitMessage(ws);
    const listingPromise=wss.attached.localFolders.listFolder(owner,deviceId,"root");
    const frame=await framePromise;
    assert.equal(frame.kind,"connector.local_browser_request");
    assert.equal(frame.operation,"list");
    assert.equal(frame.folderId,"root");
    // Opaque tokens only: no path, secret or file data in the request.
    assert.ok(!("path" in frame)&&!("token" in frame)&&!("projectId" in frame));
    assert.equal(typeof frame.requestId,"string");
    const answer={
      kind:"connector.local_browser_result",version:1,
      requestId:frame.requestId,operation:"list",folderId:"root",
      name:"KiCad Projects",parentId:null,project:false,more:false,
      folders:[{id:"child-token",name:"Motor Board",project:true}]
    };
    ws!.send(JSON.stringify(answer));
    assert.deepEqual(await listingPromise,rootListing);
  }finally{
    ws?.close();
    await wss.close();
  }
});

test("oversized folder replies within 8 KiB still reach production browse",async()=>{
  const wss=await attach("production");
  let ws:WebSocket|undefined;
  try{
    ws=await readySession(wss.port,owner);
    const framePromise=waitMessage(ws);
    const listingPromise=wss.attached.localFolders.listFolder(owner,deviceId,"root");
    const frame=await framePromise;
    const children=Array.from({length:20},(_,i)=>({
      id:"tok-"+i,name:"Project family "+i,project:false}));
    const big={kind:"connector.local_browser_result",version:1,
      requestId:frame.requestId,operation:"list",folderId:"root",
      name:"KiCad Projects",parentId:null,project:false,more:false,folders:children};
    assert.ok(JSON.stringify(big).length>1024);
    assert.ok(JSON.stringify(big).length<=8192);
    ws!.send(JSON.stringify(big));
    assert.deepEqual(await listingPromise,{...rootListing,folders:children});
  }finally{
    ws?.close();
    await wss.close();
  }
});

test("hostile or mismatched folder reply resolves unavailable and ends the session",async()=>{
  const wss=await attach("production");
  let ws:WebSocket|undefined;
  try{
    ws=await readySession(wss.port,owner);
    const framePromise=waitMessage(ws);
    const listingPromise=wss.attached.localFolders.listFolder(owner,deviceId,"root");
    const frame=await framePromise;
    const hostile={kind:"connector.local_browser_result",version:1,
      requestId:"not-the-asked-id",operation:"list",folderId:"root",
      name:"KiCad Projects",parentId:null,project:false,more:false,folders:[]};
    const replyPromise=new Promise<void>(resolve=>{ws!.once("close",()=>resolve());});
    ws!.send(JSON.stringify(hostile));
    await replyPromise;
    assert.equal(await listingPromise,null);
  }finally{
    ws?.close();
    await wss.close();
  }
});

test("local dev sandbox browse still answers only local-dev-owner",async()=>{
  const wss=await attach("local-dev");
  let ws:WebSocket|undefined;
  try{
    ws=await readySession(wss.port,"local-dev-owner");
    const framePromise=waitMessage(ws);
    const listingPromise=wss.attached.localFolders.listFolder(
      "local-dev-owner",deviceId,"root");
    const frame=await framePromise;
    assert.equal(frame.kind,"connector.local_browser_request");
    ws!.send(JSON.stringify({kind:"connector.local_browser_result",version:1,
      requestId:frame.requestId,operation:"list",folderId:"root",
      name:"KiCad Projects",parentId:null,project:false,more:false,
      folders:[{id:"child-token",name:"Motor Board",project:true}]}));
    assert.deepEqual(await listingPromise,rootListing);
  }finally{
    ws?.close();
    await wss.close();
  }
  const otherWss=await attach("local-dev");
  let other:WebSocket|undefined;
  try{
    other=await readySession(otherWss.port,owner);
    const otherSession=other;
    const nothing=new Promise<Record<string,unknown>>((resolve,reject)=>{
      otherSession.once("message",resolve);
      setTimeout(()=>reject(new Error("no frame expected")),300).unref();
    });
    assert.equal(await otherWss.attached.localFolders.listFolder(owner,deviceId,"root"),null);
    await assert.rejects(nothing,/no frame expected/);
  }finally{
    other?.close();
    await otherWss.close();
  }
});
