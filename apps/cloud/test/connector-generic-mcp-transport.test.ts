import assert from "node:assert/strict";
import test from "node:test";
import {createServer} from "node:http";
import type {AddressInfo} from "node:net";
import {randomUUID} from "node:crypto";
import {WebSocket} from "ws";
import {attachConnectorWebSocket,mcpRequestBudget} from "../src/connector-ws.js";

const deviceId="11111111-1111-4111-8111-111111111111";
const projectId="22222222-2222-4222-8222-222222222222";
const owner="owner-one";

function message(ws:WebSocket):Promise<any>{
  return new Promise((resolve,reject)=>{
    const t=setTimeout(()=>{reject(new Error("socket_response_timeout"));},6_000);
    ws.once("message",data=>{
      clearTimeout(t);
      try{resolve(JSON.parse(data.toString()));}catch(e){reject(e);}
    });
  });
}
async function send(ws:WebSocket,body:object){
  const next=message(ws);
  ws.send(JSON.stringify(body));
  return next;
}
test("generic MCP read timeout policy keeps signed writes and catalogs bounded",()=>{
  assert.deepEqual(mcpRequestBudget({method:"catalog"}),{
    timeoutMs:11_000,minSessionRemainingMs:12_000
  });
  assert.deepEqual(mcpRequestBudget({method:"call"}),{
    timeoutMs:30_000,minSessionRemainingMs:31_000
  });
  assert.deepEqual(mcpRequestBudget({method:"call",proof:{kind:"signed"}}),{
    timeoutMs:11_000,minSessionRemainingMs:12_000
  });
});

test("signed owner WS acknowledges both catalog and slow read calls",
{timeout:30_000},async()=>{
  const server=createServer((_request,response)=>{response.writeHead(404);response.end();});
  await new Promise<void>(resolve=>server.listen(0,"127.0.0.1",resolve));
  const port=(server.address() as AddressInfo).port;
  const challengeId=randomUUID(),nonce=randomUUID();
  const sessionId=randomUUID(),sessionChallenge=randomUUID();
  const attached=attachConnectorWebSocket(server,{
    publicOrigin:"http://127.0.0.1:"+port,
    sourceOf:()=>"127.0.0.1",
    proofs:{
      issue:async (_owner:string,id:string)=>({kind:"issued" as const,
        challengeId,deviceId:id,nonce,expiresAtMs:Date.now()+30_000}),
      verify:async (_owner:string,id:string)=>({kind:"verified" as const,deviceId:id}),
      cancel:async()=>undefined
    } as never,
    connections:{
      begin:async()=>({kind:"issued" as const,sessionId,deviceId,
        challengeId:sessionChallenge,nonce,binding:"A".repeat(43),
        expiresAtMs:Date.now()+30_000}),
      activate:async()=>true,
      disconnect:async()=>undefined,
      authorizeOutgoingSummary:async()=>true
    } as never,
    // Managed sessions allow serial catalog and tool calls on one signed WS.
    managedGrant:{isEnabled:async()=>true} as never
  });
  let ws:WebSocket|undefined;
  try{
    ws=new WebSocket("ws://127.0.0.1:"+port+"/api/v1/connector/ws",
      {perMessageDeflate:false});
    await new Promise<void>((resolve,reject)=>{
      ws!.once("open",resolve);ws!.once("error",reject);
    });
    const hello=await send(ws,{kind:"device.hello",version:1,
      ownerSub:owner,deviceId,mcpBridge:1,
      catalog:{schemaVersion:"1.0.0",catalogRevision:"a".repeat(64),
        operations:["mcp_bridge"]}});
    assert.equal(hello.kind,"device.challenge");
    const proof=await send(ws,{kind:"device.proof",version:1,
      signature:"A".repeat(86)});
    assert.equal(proof.kind,"connector.session_challenge");
    const ready=await send(ws,{kind:"connector.session_proof",version:1,
      signature:"A".repeat(86)});
    assert.equal(ready.kind,"connector.ready");
    assert.equal(attached.isDeviceConnected(owner,deviceId),true);
    const oauth={ownerSub:owner,clientId:"client",
      accessTokenIssuedAtSeconds:Math.floor(Date.now()/1000)};
    const requestId=randomUUID();
    const called=attached.requestMcp(oauth,deviceId,projectId,
      {requestId,method:"catalog",offset:0,toolName:"kicad_get_version"});
    const wire=await message(ws);
    assert.equal(wire.kind,"connector.mcp_request");
    assert.equal(wire.request.projectId,projectId);
    assert.equal(wire.request.method,"catalog");
    assert.equal(wire.request.toolName,"kicad_get_version");
    assert.equal(wire.sequence,1);
    const ack=await send(ws,{kind:"connector.mcp_result",version:1,
      sequence:wire.sequence,
      result:{kind:"connector.mcp_result",version:1,
        requestId,projectId,method:"catalog",ok:true,tools:[{
          name:"kicad_get_version",description:"Read installed tool",
          inputSchema:{type:"object",properties:{}},accessMode:"readonly"
        }],nextOffset:null}});
    assert.equal(ack.kind,"connector.mcp_ack");
    assert.equal(ack.requestId,requestId);
    const result=await called;
    assert.equal(result?.tools?.[0]?.name,"kicad_get_version");
    assert.equal(result?.nextOffset,null);
    // The local KiCad worker may start a native CLI DRC after its own startup.
    // A valid read completion after the original 11s deadline must not drop
    // the owner's already-authenticated Connector session.
    const slowId=randomUUID();
    const slowCall=attached.requestMcp(oauth,deviceId,projectId,{
      requestId:slowId,method:"call",toolName:"run_drc",argumentsJson:"{}"
    });
    const slowWire=await message(ws);
    assert.equal(slowWire.sequence,2);
    assert.equal(slowWire.request.method,"call");
    await new Promise<void>(resolve=>setTimeout(resolve,12_000));
    const slowAck=await send(ws,{kind:"connector.mcp_result",version:1,
      sequence:slowWire.sequence,
      result:{kind:"connector.mcp_result",version:1,
        requestId:slowId,projectId,method:"call",ok:true,
        result:{isError:false,content:[{type:"text",text:"DRC report"}]}}});
    assert.equal(slowAck.kind,"connector.mcp_ack");
    assert.equal(slowAck.requestId,slowId);
    assert.equal((await slowCall)?.ok,true);
    assert.equal(attached.isDeviceConnected(owner,deviceId),true);
  }finally{
    ws?.terminate();
    await attached.close();
    await new Promise<void>(resolve=>server.close(()=>resolve()));
  }
});
