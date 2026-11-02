import assert from "node:assert/strict";
import {createServer,type IncomingMessage} from "node:http";
import {generateKeyPairSync,randomUUID,randomBytes} from "node:crypto";
import {type AddressInfo} from "node:net";
import {test} from "node:test";
import {WebSocket} from "ws";
import {createHttpServer} from "../src/http.js";
import type {Config} from "../src/config.js";
import type {Inventory} from "../src/store.js";
import type {PairingDevicePort} from "../src/pairing-device-api.js";
import {trustedCloudflareSource,trustedPrivateSshSource,configuredDeviceSource} from "../src/trusted-ingress.js";
import {attachConnectorWebSocket} from "../src/connector-ws.js";
import {BoundConnectorConnections} from "../src/connector-transport-binding.js";

function incoming(peer:string,headers:Array<[string,string]>):IncomingMessage{
  const rawHeaders=headers.flatMap(v=>v);
  return {socket:{remoteAddress:peer},
    rawHeaders,headers:Object.fromEntries(headers.map(([key,value])=>[key.toLowerCase(),value]))
  } as unknown as IncomingMessage;
}
test("never trust client IP headers without an exact, configured proxy peer",()=>{
  assert.throws(()=>trustedCloudflareSource(undefined),/REQUIRED/);
  for(const config of ["","*","0.0.0.0/0","127.0.0.1,127.0.0.1",
    "127.0.0.1,0.0.0.0/0","127.0.0.1,invalid",
    "0.0.0.0","::"]){
    assert.throws(()=>trustedCloudflareSource(config));
  }
  const resolve=trustedCloudflareSource("172.20.0.11,::1");
  const header:[string,string]=["CF-Connecting-IP","198.51.100.70"];
  assert.equal(resolve(incoming("172.20.0.11",[header])),"198.51.100.70");
  assert.equal(resolve(incoming("172.20.0.11",[
    ["CF-Connecting-IP","::ffff:198.51.100.70"]
  ])),"198.51.100.70");
  assert.equal(resolve(incoming("172.20.0.11",[
    ["CF-Connecting-IP","::ffff:c633:6446"]
  ])),"198.51.100.70");
  assert.equal(resolve(incoming("::ffff:172.20.0.11",[header])),"198.51.100.70");
  assert.equal(resolve(incoming("::1",[header])),"198.51.100.70");
  assert.equal(resolve(incoming("172.20.0.12",[header])),null);
  assert.equal(resolve(incoming("127.0.0.1",[header])),null);
  assert.equal(resolve(incoming("172.20.0.11",[["X-Forwarded-For","198.51.100.70"]])),null);
  assert.equal(resolve(incoming("172.20.0.11",[])),null);
  assert.equal(resolve(incoming("172.20.0.11",[header,header])),null);
  assert.equal(resolve(incoming("172.20.0.11",[["CF-Connecting-IP","198.51.100.70, 8.8.8.8"]])),null);
  assert.equal(resolve(incoming("172.20.0.11",[["CF-Connecting-IP"," 198.51.100.70"]])),null);
  assert.equal(resolve(incoming("172.20.0.11",[["CF-Connecting-IP","0.0.0.0"]])),null);
  assert.equal(resolve(incoming("172.20.0.11",[["CF-Connecting-IP","%invalid"]])),null);
  assert.equal(resolve(incoming("172.20.0.11",[["CF-Connecting-IP","198.51.100.70:5432"]])),null);
});
test("IPv6 equivalent client spellings map to one PostgreSQL rate-budget key",()=>{
  const resolve=trustedCloudflareSource("2606:4700:4700:0000:0000:0000:0000:1111");
  assert.equal(resolve(incoming("2606:4700:4700::1111",[
    ["cf-connecting-ip","2001:0db8:0000:0000:0000:0000:0000:0001"]
  ])),"2001:db8::1");
  assert.equal(resolve(incoming("2606:4700:4700::1111",[
    ["CF-CONNECTING-IP","2001:db8::1"]
  ])),"2001:db8::1");
});

const config:Config={
  host:"127.0.0.1",port:0,publicOrigin:"http://127.0.0.1",
  issuer:"https://issuer.example",jwksUrl:"https://issuer.example/keys",
  audience:"http://127.0.0.1/mcp",databaseUrl:"fixture-only",allowedOrigins:[],
  managementClientId:"manager"
};
const inventory={
  isAccessTokenAllowed:async()=>false,listDevices:async()=>[],
  listProjects:async()=>[],getProject:async()=>null
} as Inventory;
async function listen(server:ReturnType<typeof createServer>){
  await new Promise<void>(resolve=>server.listen(0,"127.0.0.1",resolve));
  return {base:"http://127.0.0.1:"+(server.address() as AddressInfo).port,
    close:()=>new Promise<void>(resolve=>server.close(()=>resolve()))};
}
test("HTTP challenge refuses absent/forged Cloudflare origin even with correct body",async()=>{
  const seen:string[]=[];
  const api:PairingDevicePort={
    approved:async()=>({kind:"unavailable"}),
    issue:async source=>{
      seen.push(source);
      return {kind:"ok",data:{id:randomUUID(),userCode:"ABCDEF-123456",
        deviceCode:randomBytes(32).toString("base64url"),
        deviceFingerprint:"a".repeat(64),expiresAtMs:Date.now()+60_000}};
    },
    enroll:async()=>({kind:"unavailable"})
  };
  const allowed=trustedCloudflareSource("127.0.0.1");
  const server=createHttpServer(config, inventory, async()=>{throw Error("unused");}, {pairingDevice:api, deviceSource:allowed});
  const l=await listen(server);
  const der=generateKeyPairSync("ed25519").publicKey.export({
    format:"der",type:"spki"
  }) as Buffer;
  const body=JSON.stringify({alias:"Lab",publicKeyDer:der.toString("base64")});
  try{
    const url=l.base+"/api/v1/pairing/device/challenge";
    const request=(headers:Record<string,string>)=>fetch(url,{
      method:"POST",headers:{"content-type":"application/json",...headers},body
    });
    assert.equal((await request({})).status,403);
    assert.equal((await request({"X-Forwarded-For":"8.8.8.8"})).status,403);
    const accepted=await request({"CF-Connecting-IP":"8.8.8.8",
      "X-Forwarded-For":"127.0.0.123"});
    assert.equal(accepted.status,201);
    assert.deepEqual(seen,["8.8.8.8"]);
  }finally{await l.close();}

  const denied=trustedCloudflareSource("127.0.0.2");
  const deniedServer=createHttpServer(config, inventory, async()=>{throw Error("unused");}, {pairingDevice:api, deviceSource:denied});
  const dl=await listen(deniedServer);
  try{
    const res=await fetch(dl.base+"/api/v1/pairing/device/challenge",{
      method:"POST",headers:{"content-type":"application/json","CF-Connecting-IP":"8.8.8.8"},
      body
    });
    assert.equal(res.status,403);
    assert.deepEqual(seen,["8.8.8.8"]);
  }finally{await dl.close();}
});
test("WebSocket Upgrade rejects untrusted peer and missing CF-Connecting-IP",async()=>{
  const server=createServer((_req,res)=>{res.writeHead(404);res.end();});
  const session=new BoundConnectorConnections({
    issue:async()=>({kind:"unavailable"}),activate:async()=>({kind:"unavailable"}),
    close:async()=>true
  },{verifySignedRead:async()=>({kind:"unavailable"})});
  const l=await listen(server);
  const attach=attachConnectorWebSocket(server,{
    publicOrigin:l.base,sourceOf:trustedCloudflareSource("127.0.0.1"),
    proofs:{
      issue:async()=>({kind:"unavailable"}),
      verify:async()=>({kind:"unavailable"}),
      cancel:async()=>false
    },
    connections:session
  });
  const uri=l.base.replace("http:","ws:")+"/api/v1/connector/ws";
  function connect(headers?:Record<string,string>){
    return new Promise<WebSocket>((resolve,reject)=>{
      const ws=new WebSocket(uri,{headers,perMessageDeflate:false});
      ws.once("open",()=>resolve(ws));
      ws.once("error",reject);
    });
  }
  try{
    await assert.rejects(connect(),/403/);
    await assert.rejects(connect({"X-Forwarded-For":"8.8.8.8"}),/403/);
    const ws=await connect({"CF-Connecting-IP":"8.8.8.8"});
    assert.equal(ws.readyState,WebSocket.OPEN);
    ws.terminate();
  }finally{
    await attach.close();
    await l.close();
  }
});

test("private owner SSH ingress pins only the Docker gateway without forwarded claims",()=>{
  assert.throws(()=>trustedPrivateSshSource(undefined),/REQUIRED/);
  for(const bad of ["","*","0.0.0.0","::1","127.0.0.1","8.8.8.8",
    "172.15.1.1","172.32.1.1","10.1.1.2/32","10.1.1.2,10.1.1.3",
    "invalid"," 172.20.0.1","169.254.1.1","::ffff:172.20.0.1"]){
    assert.throws(()=>trustedPrivateSshSource(bad),bad);
  }
  const resolve=trustedPrivateSshSource("172.21.0.1");
  assert.equal(resolve(incoming("172.21.0.1",[])),"172.21.0.1");
  assert.equal(resolve(incoming("::ffff:172.21.0.1",[])),"172.21.0.1");
  assert.equal(resolve(incoming("172.21.0.2",[])),null);
  assert.equal(resolve(incoming("127.0.0.1",[])),null);
  for(const name of ["CF-Connecting-IP","X-Forwarded-For","Forwarded",
    "X-Real-IP","Tailscale-User-Login","Tailscale-User-Name"]){
    assert.equal(resolve(incoming("172.21.0.1",[[name,"198.51.100.70"]])),null,name);
  }
});

test("private SSH source is enforced by pairing HTTP even without CF headers",async()=>{
  const seen:string[]=[];
  const api:PairingDevicePort={
    approved:async()=>({kind:"unavailable"}),
    issue:async source=>{seen.push(source);return {kind:"unavailable"};},
    enroll:async()=>({kind:"unavailable"})
  };
  const resolver=trustedPrivateSshSource("172.21.0.1");
  const der=generateKeyPairSync("ed25519").publicKey.export({format:"der",type:"spki"}) as Buffer;
  const body=JSON.stringify({alias:"Owner device",publicKeyDer:der.toString("base64")});
  const server=createHttpServer(config, inventory, async()=>{throw Error("unused");}, {pairingDevice:api, deviceSource:resolver});
  const running=await listen(server);
  try{
    const response=await fetch(running.base+"/api/v1/pairing/device/challenge",{
      method:"POST",headers:{"content-type":"application/json"},body
    });
    assert.equal(response.status,403); // listening on loopback, not gateway peer
    assert.deepEqual(seen,[]);
  }finally{await running.close();}
});

test("private mode must be explicit, with exactly one pinned trust source",()=>{
  assert.throws(()=>configuredDeviceSource({}),/TRUSTED_CLOUDFLARED_PEERS_REQUIRED/);
  assert.throws(()=>configuredDeviceSource({CONNECTOR_INGRESS_MODE:"private_ssh"}),
    /TRUSTED_PRIVATE_SSH_PEER_REQUIRED/);
  assert.throws(()=>configuredDeviceSource({CONNECTOR_INGRESS_MODE:"unknown",TRUSTED_PRIVATE_SSH_PEER:"172.21.0.1"}),
    /INVALID_CONNECTOR_INGRESS_MODE/);
  assert.throws(()=>configuredDeviceSource({CONNECTOR_INGRESS_MODE:"private_ssh",
    TRUSTED_PRIVATE_SSH_PEER:"172.21.0.1",TRUSTED_CLOUDFLARED_PEERS:"172.21.0.2"}),
    /AMBIGUOUS_CONNECTOR_INGRESS_TRUST/);
  assert.throws(()=>configuredDeviceSource({TRUSTED_PRIVATE_SSH_PEER:"172.21.0.1",
    TRUSTED_CLOUDFLARED_PEERS:"172.21.0.2"}),/AMBIGUOUS_CONNECTOR_INGRESS_TRUST/);
  const legacy=configuredDeviceSource({TRUSTED_CLOUDFLARED_PEERS:"172.21.0.2"});
  assert.equal(legacy(incoming("172.21.0.2",[["CF-Connecting-IP","198.51.100.70"]])),"198.51.100.70");
  const privateMode=configuredDeviceSource({CONNECTOR_INGRESS_MODE:"private_ssh",
    TRUSTED_PRIVATE_SSH_PEER:"172.21.0.1"});
  assert.equal(privateMode(incoming("172.21.0.1",[])),"172.21.0.1");
  assert.equal(privateMode(incoming("172.21.0.2",[["CF-Connecting-IP","198.51.100.70"]])),null);
});
