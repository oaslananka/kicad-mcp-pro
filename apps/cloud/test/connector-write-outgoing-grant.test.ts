import assert from "node:assert/strict";
import {randomUUID} from "node:crypto";
import {createServer} from "node:http";
import type {AddressInfo} from "node:net";
import test from "node:test";
import {WebSocket} from "ws";
import {attachConnectorWebSocket} from "../src/connector-ws.js";

const owner="isolated-owner";
const deviceId="11111111-1111-4111-8111-111111111111";
const projectId="22222222-2222-4222-8222-222222222222";

function nextMessage(ws:WebSocket):Promise<Record<string,unknown>>{
  return new Promise((resolve,reject)=>{
    const timer=setTimeout(()=>{cleanup();reject(Error("socket_message_timeout"));},4_000);
    function onMessage(data:WebSocket.RawData){
      cleanup();
      try{resolve(JSON.parse(data.toString()) as Record<string,unknown>);}
      catch{reject(Error("invalid_socket_frame"));}
    }
    function onClose(){cleanup();reject(Error("socket_closed"));}
    function cleanup(){
      clearTimeout(timer);ws.off("message",onMessage);ws.off("close",onClose);
    }
    ws.once("message",onMessage);ws.once("close",onClose);
  });
}
function send(ws:WebSocket,frame:object):Promise<Record<string,unknown>>{
  const reply=nextMessage(ws);
  ws.send(JSON.stringify(frame));
  return reply;
}

test("revoked OAuth/client/project grant is rechecked at the final signed native WSS send",
  {timeout:15_000},async()=>{
  let grantCurrent=false;
  let delayedGate:Promise<boolean>|undefined;
  let gateEntered:(()=>void)|undefined;
  const inspected:Array<{client:string;project:string}>=[];
  const server=createServer((_req,res)=>{res.writeHead(404);res.end();});
  await new Promise<void>(resolve=>server.listen(0,"127.0.0.1",resolve));
  const port=(server.address() as AddressInfo).port;
  const attached=attachConnectorWebSocket(server,{
    publicOrigin:"http://127.0.0.1:"+port,sourceOf:()=>"127.0.0.1",
    proofs:{
      issue:async(_owner:string,id:string)=>({
        kind:"issued" as const,challengeId:randomUUID(),deviceId:id,
        nonce:randomUUID(),expiresAtMs:Date.now()+30_000
      }),
      verify:async(_owner:string,id:string)=>({kind:"verified" as const,deviceId:id}),
      cancel:async()=>undefined
    } as never,
    connections:{
      begin:async()=>({
        kind:"issued" as const,sessionId:randomUUID(),
        challengeId:randomUUID(),deviceId,
        nonce:randomUUID(),binding:"A".repeat(43),expiresAtMs:Date.now()+30_000
      }),
      activate:async()=>true,disconnect:async()=>undefined,
      // A Read grant can survive after the owner downgrades Edit. This
      // legacy read gate MUST NOT satisfy the final write authorization.
      authorizeOutgoingSummary:async()=>true,
      authorizeOutgoingWrite:async(_socket:object,oauth:{clientId:string},project:string)=>{
        inspected.push({client:oauth.clientId,project});
        if(delayedGate){gateEntered?.();return delayedGate;}
        return grantCurrent&&oauth.clientId==="approved-client"&&project===projectId;
      }
    } as never,
    managedGrant:{isEnabled:async()=>true} as never
  });
  let ws:WebSocket|undefined;
  try{
    ws=new WebSocket("ws://127.0.0.1:"+port+"/api/v1/connector/ws",
      {perMessageDeflate:false});
    await new Promise<void>((resolve,reject)=>{
      ws!.once("open",resolve);ws!.once("error",reject);
    });
    assert.equal((await send(ws,{kind:"device.hello",version:1,
      ownerSub:owner,deviceId,catalog:{
        schemaVersion:"1.0.0",catalogRevision:"a".repeat(64),
        operations:["move_footprint","mcp_bridge"]
      },mcpBridge:1})).kind,"device.challenge");
    assert.equal((await send(ws,{kind:"device.proof",version:1,
      signature:"A".repeat(86)})).kind,"connector.session_challenge");
    assert.equal((await send(ws,{kind:"connector.session_proof",version:1,
      signature:"A".repeat(86)})).kind,"connector.ready");

    const oauth={ownerSub:owner,clientId:"approved-client",
      accessTokenIssuedAtSeconds:Math.floor(Date.now()/1000)};
    const deniedId=randomUUID();
    const deniedPayload=Buffer.from(JSON.stringify({requestId:deniedId}))
      .toString("base64url");
    const rejected=await Promise.race([
      attached.requestWrite(oauth,deviceId,projectId,{payload:deniedPayload},true)
        .then(result=>({settled:true,result})),
      new Promise<{settled:false}>(resolve=>setTimeout(()=>resolve({settled:false}),240))
    ]);
    assert.deepEqual(rejected,{settled:true,result:null},
      "revoked project must fail before reserving or transmitting a signed write");
    assert.deepEqual(inspected,[{client:"approved-client",project:projectId}]);

    // A fresh owner grant permits a distinct write and preserves the initial
    // sequence, proving the denied request consumed no signed write slot.
    grantCurrent=true;
    const requestId=randomUUID();
    const payload=Buffer.from(JSON.stringify({requestId})).toString("base64url");
    const outgoing=nextMessage(ws);
    const pending=attached.requestWrite(oauth,deviceId,projectId,{payload},true);
    const frame=await outgoing;
    assert.equal(frame.kind,"connector.authorized_write");
    assert.equal(frame.sequence,1);
    assert.equal(frame.projectId,projectId);
    const ack=nextMessage(ws);
    const result={requestId,projectId,operation:"pcb_move_footprint",
      nativeCommitted:true,savedToDisk:true,diskBoardSha256:"f".repeat(64)};
    ws.send(JSON.stringify({kind:"connector.write_result",
      version:1,sequence:frame.sequence,result}));
    assert.deepEqual(await pending,result);
    assert.equal((await ack).kind,"connector.write_ack");

    // Even with the grant back, a mismatched OAuth client cannot re-use it.
    assert.equal(await attached.requestWrite({...oauth,clientId:"wrong-client"},
      deviceId,projectId,{payload},true),null);
    assert.deepEqual(inspected.at(-1),{client:"wrong-client",project:projectId});

    // Generic catalog READ can remain authorized while signed WRITE is
    // downgraded. The same outgoing Edit gate must fence proof-bearing calls.
    grantCurrent=false;
    const genericId=randomUUID();
    const signedCall={
      requestId:genericId,method:"call" as const,
      toolName:"pcb_save",argumentsJson:"{}",proof:{kind:"test-only"}
    };
    const genericDenied=await Promise.race([
      attached.requestMcp(oauth,deviceId,projectId,signedCall)
        .then(result=>({settled:true,result})),
      new Promise<{settled:false}>(resolve=>setTimeout(()=>resolve({settled:false}),240))
    ]);
    assert.deepEqual(genericDenied,{settled:true,result:null},
      "a live Read grant is not permission to send signed generic MCP WRITE");

    grantCurrent=true;
    const genericOutbound=nextMessage(ws);
    const genericPending=attached.requestMcp(oauth,deviceId,projectId,signedCall);
    const genericFrame=await genericOutbound;
    assert.equal(genericFrame.kind,"connector.mcp_request");
    assert.equal(genericFrame.sequence,2);
    assert.equal((genericFrame.request as {method:string}).method,"call");
    const genericAck=nextMessage(ws);
    ws.send(JSON.stringify({
      kind:"connector.mcp_result",version:1,sequence:genericFrame.sequence,
      result:{kind:"connector.mcp_result",version:1,
        requestId:genericId,projectId,method:"call",ok:true,
        result:{isError:false,content:[{type:"text",text:"test only"}]}}
    }));
    assert.equal((await genericPending)?.ok,true);
    assert.equal((await genericAck).kind,"connector.mcp_ack");

    // If the final DB check is pending when the owner disconnects, its
    // previously successful result cannot authorize a send on that socket.
    let releaseGate!:(allowed:boolean)=>void;
    delayedGate=new Promise<boolean>(resolve=>{releaseGate=resolve;});
    const entered=new Promise<void>(resolve=>{gateEntered=resolve;});
    const late=attached.requestWrite(oauth,deviceId,projectId,{payload},true);
    await entered;
    const closed=new Promise<void>(resolve=>ws!.once("close",()=>resolve()));
    ws.close(1000,"fixture_disconnect");
    await closed;
    releaseGate(true);
    assert.equal(await late,null);
    assert.equal(attached.isDeviceConnected(owner,deviceId),false);
  }finally{
    ws?.terminate();
    await attached.close();
    await new Promise<void>(resolve=>server.close(()=>resolve()));
  }
});
