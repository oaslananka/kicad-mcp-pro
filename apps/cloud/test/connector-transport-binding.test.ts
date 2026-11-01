import assert from "node:assert/strict";
import {randomUUID} from "node:crypto";
import {test} from "node:test";
import {BoundConnectorConnections,
  type DeviceSessionPort,type ReadAdmissionPort} from "../src/connector-transport-binding.js";

function fixture(){
  const deviceId=randomUUID(),sessionId=randomUUID(),challengeId=randomUUID();
  const ownerSub="trusted-owner",binding="B".repeat(43),nonce="N".repeat(43);
  const calls:{
    begin:number;
    close:string[];
    activation:string[];
    reads:Array<{owner:string;device:string;session:string;binding:string}>;
  }={begin:0,close:[],activation:[],reads:[]};
  const sessions:DeviceSessionPort={
    async issue(owner,device){
      calls.begin++;
      assert.equal(owner,ownerSub);assert.equal(device,deviceId);
      return {kind:"issued",sessionId,challengeId,nonce,binding,expiresAtMs:9_999_999_999};
    },
    async activate(owner,device,id,code,socketBinding,_signature){
      assert.equal(owner,ownerSub);assert.equal(device,deviceId);
      assert.equal(id,sessionId);assert.equal(code,nonce);
      calls.activation.push(socketBinding);
      return {kind:"active",sessionId,expiresAtMs:9_999_999_999};
    },
    async close(_owner,_device,id,socketBinding){
      calls.close.push(id+":"+socketBinding);
      return true;
    }
  };
  const admission:ReadAdmissionPort={
    async verifySignedRead(oauth,conn,sequence,_raw,_sig){
      calls.reads.push({owner:oauth.ownerSub,device:conn.deviceId,
        session:conn.sessionId,binding:conn.connectionBinding});
      return {kind:"accepted",sequence,
        request:{kind:"connector.read_request",version:1,
          requestId:randomUUID(),deviceId,projectId:randomUUID(),
          operation:"run_drc",deadlineUnixMs:100_000}};
    }
  };
  return {deviceId,sessionId,ownerSub,binding,nonce,calls,
    registry:new BoundConnectorConnections(sessions,admission)};
}

test("server socket object alone binds device identity and derived read authority",async()=>{
  const f=fixture(),socket={physicalSocket:true},foreignSocket={physicalSocket:true};
  const signer=Buffer.alloc(64,1),raw=Buffer.from("signed-packet");
  assert.equal((await f.registry.begin(socket,{ownerSub:f.ownerSub,deviceId:f.deviceId})).kind,"issued");
  assert.equal((await f.registry.begin(socket,{ownerSub:f.ownerSub,deviceId:f.deviceId})).kind,"unavailable");
  assert.equal(f.calls.begin,1);
  assert.equal(await f.registry.activate(foreignSocket,signer),false);
  assert.equal((await f.registry.admitRead(foreignSocket,{
    ownerSub:f.ownerSub,clientId:"client",accessTokenIssuedAtSeconds:1
  },1,raw,signer)).kind,"unavailable");
  assert.equal(await f.registry.activate(socket,signer),true);
  assert.equal(await f.registry.activate(socket,signer),false);
  const oauth={ownerSub:f.ownerSub,clientId:"verified-client",accessTokenIssuedAtSeconds:1};
  assert.equal((await f.registry.admitRead(socket,{...oauth,ownerSub:"foreign-owner"},1,raw,signer)).kind,"unavailable");
  assert.equal((await f.registry.admitRead(socket,oauth,1,raw,signer)).kind,"accepted");
  assert.deepEqual(f.calls.reads,[{owner:f.ownerSub,device:f.deviceId,
    session:f.sessionId,binding:f.binding}]);
  await f.registry.disconnect(socket);
  await f.registry.disconnect(socket);
  assert.equal(f.calls.close.length,1);
  assert.equal((await f.registry.admitRead(socket,oauth,2,raw,signer)).kind,"unavailable");
});

test("disconnect while DB issue is pending burns orphaned challenge",async()=>{
  let resolveIssue!: (value:Awaited<ReturnType<DeviceSessionPort["issue"]>>)=>void;
  const pending=new Promise<Awaited<ReturnType<DeviceSessionPort["issue"]>>>(
    resolve=>{resolveIssue=resolve;});
  let closed=0;
  const sessions:DeviceSessionPort={
    issue:async()=>pending,
    activate:async()=>({kind:"unavailable"}),
    close:async()=>{closed++;return true;}
  };
  const gate:ReadAdmissionPort={
    verifySignedRead:async()=>({kind:"unavailable"})
  };
  const registry=new BoundConnectorConnections(sessions,gate),socket={};
  const start=registry.begin(socket,{ownerSub:"owner",deviceId:randomUUID()});
  await registry.disconnect(socket);
  resolveIssue({kind:"issued",sessionId:randomUUID(),challengeId:randomUUID(),
    nonce:"N",binding:"B",expiresAtMs:1234});
  assert.equal((await start).kind,"unavailable");
  assert.equal(closed,1);
});

test("a read completing after disconnect is never admitted to caller",async()=>{
  const base=fixture(),socket={},signer=Buffer.alloc(64),bytes=Buffer.from("payload");
  let resolveRead!: (value:Awaited<ReturnType<ReadAdmissionPort["verifySignedRead"]>>)=>void;
  const wait=new Promise<Awaited<ReturnType<ReadAdmissionPort["verifySignedRead"]>>>(
    resolve=>{resolveRead=resolve;});
  const sessions:DeviceSessionPort={
    issue:async()=>({kind:"issued",sessionId:base.sessionId,challengeId:randomUUID(),
      nonce:base.nonce,binding:base.binding,expiresAtMs:100_000}),
    activate:async()=>({kind:"active",sessionId:base.sessionId,expiresAtMs:100_000}),
    close:async()=>true
  };
  const admission:ReadAdmissionPort={verifySignedRead:async()=>wait};
  const registry=new BoundConnectorConnections(sessions,admission);
  await registry.begin(socket,{ownerSub:base.ownerSub,deviceId:base.deviceId});
  await registry.activate(socket,signer);
  const request=registry.admitRead(socket,{ownerSub:base.ownerSub,
    clientId:"client",accessTokenIssuedAtSeconds:1},1,bytes,signer);
  await registry.disconnect(socket);
  resolveRead({kind:"accepted",sequence:1,request:{
    kind:"connector.read_request",version:1,requestId:randomUUID(),
    deviceId:base.deviceId,projectId:randomUUID(),
    operation:"run_drc",deadlineUnixMs:100_000}});
  assert.equal((await request).kind,"unavailable");
});
