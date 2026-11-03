import assert from "node:assert/strict";
import {test} from "node:test";
import {handleCandidate} from "../infra/edge-worker/candidate.mjs";

const HOST="https://kicad-mcp-pro.oaslananka.dev";
const R=[
  ["POST","/api/v1/pairing/device/challenge","CHALLENGE_IP","CHALLENGE_GLOBAL"],
  ["POST","/api/v1/pairing/device/redeem","REDEEM_IP","REDEEM_GLOBAL"],
  ["GET","/api/v1/connector/ws","WSS_IP","WSS_GLOBAL"]
];
function request(method,path,ip="198.51.100.70",other={}){
  const headers={"CF-Connecting-IP":ip,...other};
  if(method==="GET")headers.Upgrade="websocket";
  return new Request(HOST+path,{method,headers});
}
function bindings(){
  const calls=[];
  const env={};
  for(const name of R.flatMap(r=>r.slice(2))){
    Object.defineProperty(env,name,{
      enumerable:true,configurable:true,writable:true,
      value:{limit:async({key})=>{calls.push({name,key});return {success:true}}}
    });
  }
  return {env,calls};
}
for(const [method,path,ipKey,globalKey]of R){
  test("bounded, exact, valid "+path+" forwards one unmodified request",async()=>{
    const {env,calls}=bindings();
    const r=request(method,path);
    let forwarded=0;
    const result=await handleCandidate(r,env,async incoming=>{
      forwarded++;
      assert.strictEqual(incoming,r);
      return new Response(null,{status:204});
    });
    assert.equal(result.status,204);
    assert.equal(forwarded,1);
    assert.deepEqual(calls,[
      {name:ipKey,key:(path.endsWith("/ws")?"wss":path.endsWith("/redeem")?"redeem":"challenge")+":198.51.100.70"},
      {name:globalKey,key:(path.endsWith("/ws")?"wss":path.endsWith("/redeem")?"redeem":"challenge")+":all"}
    ]);
  });
  test("rejects missing bindings without forwarding "+path,async()=>{
    let called=0;
    const result=await handleCandidate(request(method,path),{},()=>{called++;});
    assert.equal(result.status,503);assert.equal(called,0);
  });
  test("rejects denied actor quota "+path,async()=>{
    const {env}=bindings();
    Object.defineProperty(env,ipKey,{value:{limit:async()=>({success:false})}});
    const result=await handleCandidate(request(method,path),env,()=>{throw Error("must not forward")});
    assert.equal(result.status,429);
  });
  test("rejects denied global quota "+path,async()=>{
    const {env}=bindings();
    Object.defineProperty(env,globalKey,{value:{limit:async()=>({success:false})}});
    const result=await handleCandidate(request(method,path),env,()=>{throw Error("must not forward")});
    assert.equal(result.status,429);
  });
  test("binding failure fails closed "+path,async()=>{
    const {env}=bindings();
    Object.defineProperty(env,ipKey,{value:{limit:async()=>{throw new Error("unavailable")}}});
    const result=await handleCandidate(request(method,path),env,()=>{throw Error("must not forward")});
    assert.equal(result.status,503);
  });
}
test("unrelated paths, other hostnames, plaintext HTTP, query parameters and wrong methods never forward",async()=>{
  const {env}=bindings();
  const samples=[
    new Request(HOST+"/api/v1/pairing/device/challenge?bypass=1",{method:"POST"}),
    new Request(HOST+"/api/v1/pairing/device/redeem",{method:"GET"}),
    new Request(HOST+"/health"),
    new Request(HOST.replace("https:","http:")+"/api/v1/connector/ws"),
    new Request(HOST.replace("kicad-mcp-pro","unrelated")+"/api/v1/pairing/device/challenge",{method:"POST"})
  ];
  for(const req of samples){
    const result=await handleCandidate(req,env,()=>{throw Error("forwarded invalid request")});
    assert.ok([404,405].includes(result.status));
  }
});
test("WebSocket upgrade must actually be requested",async()=>{
  const {env}=bindings();
  const result=await handleCandidate(
    new Request(HOST+"/api/v1/connector/ws",{headers:{"CF-Connecting-IP":"198.51.100.70"}}),
    env,()=>{throw Error("must not forward")});
  assert.equal(result.status,426);
});
test("missing, invalid and comma-delimited claimed visitor addresses fail closed",async()=>{
  const {env,calls}=bindings();
  for(const ip of ["", "garbage", "198.51.100.70, 8.8.8.8",
    "0.0.0.0","::","198.51.100.70:1234","2001::db8::123",
    "2001:db8::1%zone"]){
    const r=request("POST",R[0][1],ip);
    const result=await handleCandidate(r,env,()=>{throw Error("must not forward")});
    assert.equal(result.status,403,ip);
  }
  assert.equal(calls.length,0);
});
test("mapped IPv6 aliases use the same actor key",async()=>{
  const {env,calls}=bindings();
  await handleCandidate(request("POST",R[0][1],"::ffff:198.51.100.70"),env,async()=>new Response(null,{status:204}));
  await handleCandidate(request("POST",R[0][1],"::ffff:c633:6446"),env,async()=>new Response(null,{status:204}));
  assert.equal(calls[0].key,calls[2].key);
});
test("distinct IPv6 formats normalize to a single rate-budget key",async()=>{
  const {env,calls}=bindings();
  for(const ip of ["2001:0db8:0000:0000:0000:0000:0000:0001","2001:db8::1"]){
    const result=await handleCandidate(request("POST",R[0][1],ip),env,async()=>new Response(null,{status:204}));
    assert.equal(result.status,204);
  }
  assert.equal(calls[0].key,calls[2].key);
});

test("unexpected approved-origin forwarding errors fail closed",async()=>{
  const {env}=bindings();
  const response=await handleCandidate(request("POST",R[0][1]),env,
    async()=>{throw new Error("upstream offline");});
  assert.equal(response.status,503);
  assert.equal(response.headers.get("Cache-Control"),"no-store");
});
