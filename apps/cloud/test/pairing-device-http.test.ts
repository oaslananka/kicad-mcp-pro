import assert from "node:assert/strict";
import {createHash,generateKeyPairSync,randomBytes,randomUUID} from "node:crypto";
import {test} from "node:test";
import type {AddressInfo} from "node:net";
import type {Server} from "node:http";
import {createHttpServer} from "../src/http.js";
import type {Config} from "../src/config.js";
import type {Inventory} from "../src/store.js";
import type {PairingDevicePort} from "../src/pairing-device-api.js";

const config:Config={
  host:"127.0.0.1",port:0,publicOrigin:"http://127.0.0.1",
  issuer:"https://issuer.example",jwksUrl:"https://issuer.example/keys",
  audience:"http://127.0.0.1/mcp",databaseUrl:"fixture-only",
  allowedOrigins:[],managementClientId:"manager"
};
const inventory={
  isAccessTokenAllowed:async()=>false,listDevices:async()=>[],
  listProjects:async()=>[],getProject:async()=>null
} as Inventory;
const id=randomUUID(),secret=randomBytes(32).toString("base64url");
const key=generateKeyPairSync("ed25519")
  .publicKey.export({format:"der",type:"spki"}) as Buffer;
async function listener(server:Server){
  await new Promise<void>(resolve=>server.listen(0,"127.0.0.1",resolve));
  return {
    origin:"http://127.0.0.1:"+(server.address() as AddressInfo).port,
    close:()=>new Promise<void>(resolve=>server.close(()=>resolve()))
  };
}
test("device endpoints are absent unless separately wired",async()=>{
  const server=createHttpServer(config, inventory, async()=>{throw Error("not called");});
  const l=await listener(server);
  try{
    for(const path of ["/challenge","/status","/redeem"]){
      const response=await fetch(l.origin+"/api/v1/pairing/device"+path,{
        method:"POST",headers:{"Content-Type":"application/json"},
        body:JSON.stringify({deviceId:id})
      });
      assert.equal(response.status,404);
    }
  }finally{await l.close();}
});
test("strict device-only HTTP denies browser, spoofed identity and oversized traffic",async()=>{
  const calls:string[]=[];
  const api:PairingDevicePort={
    approved:async()=>({kind:"unavailable"}),
    async issue(source,alias,publicKeyDer){
      calls.push("issue:"+source+":"+alias);
      assert.deepEqual(publicKeyDer,key);
      return {kind:"ok",data:{id,userCode:"ABCDEF-123456",deviceCode:secret,
        deviceFingerprint:createHash("sha256").update(key).digest("hex"),
        expiresAtMs:Date.now()+60_000}};
    },
    async enroll(source,challengeId,code,signature){
      calls.push("enroll:"+source+":"+challengeId);
      assert.equal(code,secret);assert.equal(signature.length,64);
      return {kind:"ok",data:{kind:"enrolled",deviceId:randomUUID(),
        ownerSub:"owner",deviceFingerprint:"a".repeat(64)}};
    }
  };
  const server=createHttpServer(config, inventory, async()=>{throw Error("not called");}, {pairingDevice:api, deviceSource:req=>req.socket.remoteAddress??null});
  const l=await listener(server),issue=l.origin+"/api/v1/pairing/device/challenge";
  const good=JSON.stringify({alias:"KiCad Test",publicKeyDer:key.toString("base64")});
  try{
    const wrongMethod=await fetch(issue);
    assert.equal(wrongMethod.status,405);
    const browser=await fetch(issue,{method:"POST",headers:{
      "Content-Type":"application/json",Origin:"https://hostile.example"
    },body:good});
    assert.equal(browser.status,403);
    const query=await fetch(issue+"?token=secret",{method:"POST",headers:{
      "Content-Type":"application/json"
    },body:good});
    assert.equal(query.status,403);
    const cookies=await fetch(issue,{method:"POST",headers:{
      "Content-Type":"application/json",Cookie:"session=attacker"
    },body:good});
    assert.equal(cookies.status,403);
    const polluted=await fetch(issue,{method:"POST",headers:{
      "Content-Type":"application/json"
    },body:JSON.stringify({alias:"KiCad Test",publicKeyDer:key.toString("base64"),
      projectPath:"/private/board"})});
    assert.equal(polluted.status,400);
    const huge=await fetch(issue,{method:"POST",headers:{
      "Content-Type":"application/json"
    },body:"x".repeat(5000)});
    assert.equal(huge.status,413);
    assert.deepEqual(calls,[]);
    const response=await fetch(issue,{method:"POST",headers:{
      "Content-Type":"application/json","X-Forwarded-For":"203.0.113.7"
    },body:good});
    assert.equal(response.status,201);
    assert.equal(response.headers.get("cache-control"),"no-store");
    const received=await response.json() as Record<string,unknown>;
    assert.equal(received.challengeId,id);
    assert.equal(received.deviceCode,secret);
    const complete=new URL(String(received.verificationUriComplete));
    assert.equal(complete.pathname,"/devices/pairing");
    assert.equal(complete.search,"");
    assert.equal(new URLSearchParams(complete.hash.slice(1)).get("challenge"),id);
    assert.equal(new URLSearchParams(complete.hash.slice(1)).get("code"),"ABCDEF-123456");
    assert.ok(!String(received.verificationUriComplete).includes(secret));
    assert.deepEqual(calls,["issue:127.0.0.1:KiCad Test"]);
    const statusPath=l.origin+"/api/v1/pairing/device/status";
    const invalidStatus=await fetch(statusPath,{method:"POST",headers:{
      "Content-Type":"application/json"
    },body:JSON.stringify({challengeId:id,deviceCode:secret,
      signature:"x".repeat(85)})});
    assert.equal(invalidStatus.status,400);
    const crossOriginStatus=await fetch(statusPath,{method:"POST",headers:{
      "Content-Type":"application/json",Origin:"https://attacker.example"
    },body:JSON.stringify({challengeId:id,deviceCode:secret,
      signature:randomBytes(64).toString("base64url")})});
    assert.equal(crossOriginStatus.status,403);
    const redeem=await fetch(l.origin+"/api/v1/pairing/device/redeem",{
      method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify({challengeId:id,deviceCode:secret,
        signature:randomBytes(64).toString("base64url")})
    });
    assert.equal(redeem.status,200);
    const body=await redeem.json() as Record<string,unknown>;
    assert.equal(body.enabled,false);
    assert.equal(calls.length,2);
    assert.equal(calls[1],"enroll:127.0.0.1:"+id);
  }finally{await l.close();}
});
test("redemption rejects incorrect signature and code encoding before store",async()=>{
  let called=false;
  const api:PairingDevicePort={
    approved:async()=>({kind:"unavailable"}),
    issue:async()=>({kind:"unavailable"}),
    enroll:async()=>{called=true;return {kind:"unavailable"};}
  };
  const server=createHttpServer(config, inventory, async()=>{throw Error("not called");}, {pairingDevice:api, deviceSource:req=>req.socket.remoteAddress??null});
  const l=await listener(server);
  try{
    const base=l.origin+"/api/v1/pairing/device/redeem";
    const invalid=await fetch(base,{method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify({challengeId:id,deviceCode:secret,signature:"A".repeat(85)+"B"})});
    assert.equal(invalid.status,400);
    assert.equal(called,false);
    const wrong=await fetch(base,{method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify({challengeId:id,deviceCode:secret,
        signature:randomBytes(64).toString("base64url")})});
    assert.equal(wrong.status,400);
    assert.equal(called,true);
    assert.deepEqual(await wrong.json(),{error:"unavailable"});
  }finally{await l.close();}
});
