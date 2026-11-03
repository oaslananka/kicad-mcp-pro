import assert from "node:assert/strict";
import {randomUUID} from "node:crypto";
import {createServer} from "node:http";
import type {AddressInfo} from "node:net";
import {test} from "node:test";
import {WebSocket} from "ws";
import {attachConnectorWebSocket,type DeviceProofPort} from "../src/connector-ws.js";
import type {BoundConnectorConnections} from "../src/connector-transport-binding.js";

// A purely isolated socket and injected asynchronous grant check: no DB,
// OAuth identity, public ingress, or production deployment is contacted.
function nextFrame(ws:WebSocket):Promise<Record<string,unknown>>{
  return new Promise((resolve,reject)=>{
    const timer=setTimeout(()=>{cleanup();reject(Error("SOCKET_TIMEOUT"));},4000);
    function onMessage(data:WebSocket.RawData){
      cleanup();
      try{resolve(JSON.parse(data.toString()) as Record<string,unknown>);}
      catch{reject(Error("BAD_JSON"));}
    }
    function onClose(){cleanup();reject(Error("SOCKET_CLOSED"));}
    function cleanup(){
      clearTimeout(timer);ws.off("message",onMessage);ws.off("close",onClose);
    }
    ws.once("message",onMessage);ws.once("close",onClose);
  });
}

for(const scenario of ["missing-owner-consent","rejected-owner-consent",
  "stalled-owner-consent","approved-one-shot","expired-deadline","stalled-grant",
  "disconnected-grant","stalled-preflight","disconnected-preflight",
  "rejected-preflight","rejected-final-grant"] as const){
test(scenario==="missing-owner-consent" ?
  "unavailable independent owner approval must deny before Cloud dispatch" :
  scenario==="rejected-owner-consent" ?
  "independent owner refusal must prevent read dispatch even with a valid device and grant" :
  scenario==="stalled-owner-consent" ?
  "unresponsive owner verifier cannot leave a Cloud read pending or send metadata" :
  scenario==="approved-one-shot" ?
  "independently approved synthetic one-shot binds exact request and sends only one summary" :
  scenario==="expired-deadline" ?
  "a result finishing its async grant check after request deadline is never delivered" :
  scenario==="stalled-grant" ?
  "read timeout remains armed while the last DB grant check is pending" :
  scenario==="disconnected-grant" ?
  "closed WebSocket releases HTTP wait even if final DB check is pending" :
  scenario==="stalled-preflight" ?
  "initial DB grant stall cannot hold an HTTP read forever" :
  scenario==="disconnected-preflight" ?
  "closed WebSocket releases HTTP wait during the initial DB grant" :
  scenario==="rejected-preflight" ?
  "rejected initial DB grant fails closed without read dispatch" :
  "rejected final DB grant never ACKs or releases read metadata",
  {timeout:12_000},async()=>{
  const owner="synthetic-owner",device=randomUUID(),project=randomUUID();
  const session=randomUUID(),challenge=randomUUID();
  const proofs={
    issue:async()=>({kind:"issued",challengeId:challenge,deviceId:device,
      nonce:"N".repeat(43),expiresAtMs:Date.now()+60_000}),
    verify:async()=>({kind:"verified",deviceId:device}),
    cancel:async()=>true
  } as unknown as DeviceProofPort;
  let resolveSecond!:(allowed:boolean)=>void;
  const delayedSecond=new Promise<boolean>(resolve=>{resolveSecond=resolve;});
  let signalSecond!:()=>void;
  const secondStarted=new Promise<void>(resolve=>{signalSecond=resolve;});
  let checks=0;
  let approvedRequestId:string|undefined;
  const connections={
    begin:async()=>({kind:"issued",sessionId:session,challengeId:randomUUID(),
      nonce:"N".repeat(43),binding:"B".repeat(43),expiresAtMs:Date.now()+60_000}),
    activate:async()=>true,
    authorizeOutgoingSummary:async()=>{
      checks++;
      if(scenario==="rejected-preflight"&&checks===1)
        throw Error("synthetic DB authorization rejection");
      if(checks===1 && scenario!=="stalled-preflight" &&
         scenario!=="disconnected-preflight")return true;
      signalSecond();
      if(scenario==="rejected-final-grant")
        throw Error("synthetic final DB authorization rejection");
      return delayedSecond;
    },
    disconnect:async()=>{}
  } as unknown as BoundConnectorConnections;
  const http=createServer((_request,response)=>{response.writeHead(404);response.end();});
  await new Promise<void>(resolve=>http.listen(0,"127.0.0.1",resolve));
  const port=(http.address() as AddressInfo).port;
  const relay=attachConnectorWebSocket(http,{
    publicOrigin:"http://127.0.0.1:"+port,
    sourceOf:()=>"127.0.0.1",proofs,connections,
    ...(scenario==="missing-owner-consent"?{}:{
      ownerConsent:{consume:async(scope:{
        oauth:{ownerSub:string;clientId:string};deviceId:string;projectId:string;
        requestId:string;origin:string;operation:string;expiresAtUnixMs:number;
      })=>{
        // Synthetic port. Real production has no owner verifier configured.
        assert.equal(scope.oauth.ownerSub,owner);
        assert.equal(scope.oauth.clientId,"synthetic-client");
        assert.equal(scope.deviceId,device);
        assert.equal(scope.projectId,project);
        assert.equal(scope.operation,"project_summary");
        assert.equal(scope.origin,"http://127.0.0.1:"+port);
        assert.match(scope.requestId,/^[0-9a-f-]{36}$/);
        approvedRequestId=scope.requestId;
        assert.ok(scope.expiresAtUnixMs>Date.now());
        if(scenario==="rejected-owner-consent")return false;
        if(scenario==="stalled-owner-consent")return new Promise<boolean>(()=>{});
        return true;
      }}
    })
  });
  let ws:WebSocket|undefined;
  const originalNow=Date.now;
  const originalTimeout=globalThis.setTimeout;
  try{
    ws=await new Promise<WebSocket>((resolve,reject)=>{
      const socket=new WebSocket("ws://127.0.0.1:"+port+"/api/v1/connector/ws",{perMessageDeflate:false});
      socket.once("open",()=>resolve(socket));
      socket.once("error",reject);
    });
    let next=nextFrame(ws);
    ws.send(JSON.stringify({kind:"device.hello",version:1,ownerSub:owner,deviceId:device}));
    assert.equal((await next).kind,"device.challenge");
    next=nextFrame(ws);
    ws.send(JSON.stringify({kind:"device.proof",version:1,
      signature:Buffer.alloc(64,3).toString("base64url")}));
    assert.equal((await next).kind,"connector.session_challenge");
    next=nextFrame(ws);
    ws.send(JSON.stringify({kind:"connector.session_proof",version:1,
      signature:Buffer.alloc(64,4).toString("base64url")}));
    assert.equal((await next).kind,"connector.ready");
    const oauth={
      ownerSub:owner,clientId:"synthetic-client",
      accessTokenIssuedAtSeconds:Math.floor(Date.now()/1000)
    };
    const prepared=relay.prepareOwnerSummary(oauth,device,project);
    if(scenario==="missing-owner-consent")assert.equal(prepared,null);
    else assert.ok(prepared,"Each permitted synthetic test must explicitly prepare an intent");
    assert.equal(await relay.requestSummary(oauth,device,project),null,
      "Direct legacy read without prepared consent must always fail closed");

    if(scenario==="missing-owner-consent"||scenario==="rejected-owner-consent"||
      scenario==="stalled-owner-consent"){
      let requestSent=false;
      ws.on("message",()=>{requestSent=true;});
      const closed=new Promise<number>(resolve=>ws!.once("close",resolve));
      if(scenario==="stalled-owner-consent"){
        globalThis.setTimeout=((...args:Parameters<typeof setTimeout>)=>{
          const [handler,delay,...rest]=args;
          return originalTimeout(handler,delay===8_000?80:delay,...rest);
        }) as typeof setTimeout;
      }
      const attempt=relay.requestSummary(oauth,device,project,prepared??undefined);
      globalThis.setTimeout=originalTimeout;
      const result=await Promise.race([
        attempt,
        new Promise<"missing-consent-not-bounded">(resolve=>
          originalTimeout(()=>resolve("missing-consent-not-bounded"),350))
      ]);
      assert.equal(result,null,"without trusted owner approval no read is permitted");
      assert.equal(requestSent,false,"no read can cross WSS without owner consent");
      assert.equal(checks,0,"the grant check must not substitute for owner consent");
      if(scenario!=="missing-owner-consent")assert.equal(await closed,1008);
      return;
    }
    if(scenario==="stalled-preflight"||
       scenario==="disconnected-preflight"||scenario==="rejected-preflight"){
      let requestSent=false;
      ws.on("message",()=>{requestSent=true;});
      const closed=new Promise<number>(resolve=>ws!.once("close",resolve));
      if(scenario==="stalled-preflight"){
        globalThis.setTimeout=((...args:Parameters<typeof setTimeout>)=>{
          const [handler,delay,...rest]=args;
          return originalTimeout(handler,delay===8_000?80:delay,...rest);
        }) as typeof setTimeout;
      }
      const preflight=relay.requestSummary(oauth,device,project,prepared??undefined);
      // The owner-consent step adds an async boundary. Keep the accelerated
      // test clock installed until DB preflight has actually started and
      // registered its watchdog; otherwise this measures the wrong timer.
      if(scenario!=="rejected-preflight")await secondStarted;
      globalThis.setTimeout=originalTimeout;
      if(scenario==="disconnected-preflight")ws.terminate();
      const outcome=await Promise.race([
        preflight.then(value=>value,()=> "preflight-rejected" as const),
        new Promise<"preflight-not-bounded">(resolve=>
          originalTimeout(()=>resolve("preflight-not-bounded"),350))
      ]);
      assert.equal(outcome,null,"preflight must fail closed without read dispatch");
      assert.equal(requestSent,false,"preflight failure must not dispatch a read");
      assert.equal(await closed,scenario==="disconnected-preflight"?1006:1008,
        "failed preflight must close device session");
      resolveSecond(false);
      return;
    }
    next=nextFrame(ws);
    if(scenario==="stalled-grant"){
      // Speed up only the server's 12s request watchdog; never change its
      // authorization deadline or alter any production code.
      globalThis.setTimeout=((...args:Parameters<typeof setTimeout>)=>{
        const [handler,delay,...rest]=args;
        return originalTimeout(handler,delay===12_000?80:delay,...rest);
      }) as typeof setTimeout;
    }
    const pending=relay.requestSummary(oauth,device,project,prepared??undefined);
    const sent=await next;
    globalThis.setTimeout=originalTimeout;
    assert.equal(sent.kind,"connector.authorized_read");
    const request=sent.request as Record<string,unknown>;
    assert.equal(approvedRequestId,request.requestId,
      "owner assertion must consume the exact WSS read request ID");
    const deadline=request.deadlineUnixMs as number;
    const reply={kind:"connector.read_result",version:1,sequence:1,
      result:{kind:"connector.local_read_preview",version:1,
        requestId:request.requestId,projectId:project,operation:"project_summary",
        files:{projectPresent:true,boardPresent:false,schematicPresent:false}}};
    const closed=new Promise<number>(resolve=>ws!.once("close",resolve));
    let ackDelivered=false;
    ws.on("message",data=>{
      const frame=JSON.parse(data.toString()) as Record<string,unknown>;
      if(frame.kind==="connector.read_ack")ackDelivered=true;
    });
    ws.send(JSON.stringify(reply));
    await secondStarted;
    if(scenario==="approved-one-shot"){
      resolveSecond(true);
      assert.deepEqual(await pending,reply.result);
      assert.equal(await closed,1000);
      assert.equal(ackDelivered,true,"one acknowledged summary only");
      assert.equal(checks,2);
      assert.equal(await relay.requestSummary({ownerSub:owner,clientId:"synthetic-client",
        accessTokenIssuedAtSeconds:Math.floor(Date.now()/1000)},device,project),null,
        "completed one-shot may not be reused");
      return;
    }
    if(scenario==="expired-deadline"){
      // The time of the authorization result (not only its start) matters.
      Date.now=()=>deadline+1;
      resolveSecond(true);
      assert.equal(await pending,null,
        "an approved result that outlives its signed deadline must be discarded");
    }else if(scenario==="rejected-final-grant"){
      assert.equal(await pending,null,
        "final DB authorization failures must be denied before ACK");
    }else if(scenario==="stalled-grant"){
      // The final database grant can hang: the independent request budget
      // must complete with null without ever waiting for DB resolution.
      const state=await Promise.race([
        pending, new Promise<"timeout-not-armed">(resolve=>
          originalTimeout(()=>resolve("timeout-not-armed"),350))
      ]);
      assert.equal(state,null,"the in-flight final grant must retain its watchdog");
      resolveSecond(true);
    }else{
      // No read-result relay promise should survive a device disconnect.
      ws.terminate();
      const state=await Promise.race([
        pending, new Promise<"close-not-settled">(resolve=>
          originalTimeout(()=>resolve("close-not-settled"),350))
      ]);
      assert.equal(state,null,"closed device must settle a pending Cloud read");
      resolveSecond(false);
    }
    assert.equal(checks,2);
    assert.equal(await closed,scenario==="disconnected-grant"?1006:1008,
      "expired or disconnected read must close without an ACK");
    assert.equal(ackDelivered,false,"never acknowledge an expired metadata response");
  }finally{
    Date.now=originalNow;
    globalThis.setTimeout=originalTimeout;
    resolveSecond(false);
    ws?.terminate();
    await relay.close();
    await new Promise<void>(resolve=>http.close(()=>resolve()));
  }
});
}
