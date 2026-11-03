import assert from "node:assert/strict";
import {test} from "node:test";
import {createHttpServer} from "../src/http.js";
import type {Config} from "../src/config.js";
import type {Inventory} from "../src/store.js";
import type {BrowserIdentity} from "../src/browser.js";
import type {PairingReviewPort} from "../src/pairing-review.js";
import type {AddressInfo} from "node:net";

const config:Config={
  host:"127.0.0.1",port:0,publicOrigin:"http://127.0.0.1",
  issuer:"https://issuer.example",jwksUrl:"https://issuer.example/keys",
  audience:"http://127.0.0.1/mcp",databaseUrl:"unused",allowedOrigins:[],
  managementClientId:"management"
};
const inventory={
  listDevices:async()=>[],listProjects:async()=>[],
  getProject:async()=>null,isAccessTokenAllowed:async()=>false
} as Inventory;
const identity={
  $context:Promise.resolve({secret:"synthetic-http-pairing-signing-secret-32-chars"}),
  handler:async()=>new Response(null,{status:404}),
  api:{getSession:async()=>({user:{id:"owner-a"},session:{id:"test-session"}})}
} as unknown as BrowserIdentity;
test("pairing browser route only exists behind built-in identity",async()=>{
  const responses:number[]=[];
  for(const enabled of [false,true]){
    const stub:PairingReviewPort={review:async()=> "unavailable"};
    const server=createHttpServer(config, inventory, async()=>{throw Error("unused");}, {identity:enabled?identity:undefined, pairings:enabled?stub:undefined});
    await new Promise<void>(resolve=>server.listen(0,"127.0.0.1",resolve));
    try{
      const port=(server.address() as AddressInfo).port;
      const res=await fetch("http://127.0.0.1:"+port+"/devices/pairing");
      responses.push(res.status);
      if(enabled){
        const content=await res.text();
        assert.match(content,/Pairing challenge ID/);
        assert.match(res.headers.get("set-cookie")??"",/SameSite=Strict/);
      }
    }finally{await new Promise<void>(resolve=>server.close(()=>resolve()));}
  }
  assert.deepEqual(responses,[404,200]);
});
