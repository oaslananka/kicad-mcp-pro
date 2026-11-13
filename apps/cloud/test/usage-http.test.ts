import assert from "node:assert/strict";
import {timingSafeEqual} from "node:crypto";
import {test} from "node:test";
import {createHttpServer} from "../src/http.js";
import type {Config} from "../src/config.js";
import type {Inventory,Device,Project} from "../src/store.js";
import type {Actor,Verifier} from "../src/auth.js";
import {PgUsage} from "../src/usage.js";
import {inIsolatedDatabase} from "./isolated-db.js";
import pg from "pg";

const url=process.env.TEST_DATABASE_URL;
const projectId="3fa85f64-5717-4562-b3fc-2c963f66afa6";
const mockProject:Project={
  id:projectId,alias:"USB-C Controller",
  deviceId:"d108b5f4-22f2-4b3c-b62d-55163fa34814",
  enabled:true,maxMode:"readonly",available:false,
  reason:"cloud_read_not_enabled"
};
const inventory:Inventory={
  async isAccessTokenAllowed(){return true;},
  async listDevices(owner,clientId):Promise<Device[]>{
    return owner==="user-a"&&clientId==="test-client"
      ?[{id:mockProject.deviceId,alias:"Workstation",enabled:true,
        lastSeenAt:null,connected:false}]
      :[];
  },
  async listProjects(owner,clientId){
    return owner==="user-a"&&clientId==="test-client"?[mockProject]:[];
  },
  async getProject(owner,clientId,id){
    return owner==="user-a"&&clientId==="test-client"&&id===projectId?mockProject:null;
  }
};
const verify:Verifier=async token=>{
  const given=Buffer.from(token),expected=Buffer.from("test-user-a");
  if(given.length!==expected.length||!timingSafeEqual(given,expected))
    throw new Error("invalid");
  const actor:Actor={
    sub:"user-a",clientId:"test-client",
    scopes:new Set(["projects:read"]),issuedAt:Math.floor(Date.now()/1000)};
  return actor;
};
const config:Config={
  host:"127.0.0.1",port:0,publicOrigin:"http://127.0.0.1",
  issuer:"https://issuer.example",jwksUrl:"https://issuer.example/keys",
  audience:"http://127.0.0.1/mcp",databaseUrl:"unused",
  allowedOrigins:[],managementClientId:"portal-client"
};
const headers=(method?:string,name?:string)=>({
  "Authorization":"Bearer test-user-a",
  "Content-Type":"application/json",
  "Accept":"application/json, text/event-stream",
  "MCP-Protocol-Version":"2026-07-28",
  ...(method?{"Mcp-Method":method}:{}),
  ...(name?{"Mcp-Name":name}:{})
});
function payload(method:string,params:object={}){
  return JSON.stringify({jsonrpc:"2.0",id:1,method,params:{
    ...params,_meta:{"io.modelcontextprotocol/clientInfo":{name:"usage-test",version:"1.0.0"},
      "io.modelcontextprotocol/protocolVersion":"2026-07-28",
      "io.modelcontextprotocol/clientCapabilities":{}}}});
}

test("real MCP tool calls record measured usage on the served HTTP path",
  {skip:!url},async()=>{
  await inIsolatedDatabase(url!,["022_usage_and_owner_api.pgsql"],async db=>{
    const usage=new PgUsage(db);
    const server=createHttpServer(config,inventory,verify,{usage});
    await new Promise<void>(resolve=>server.listen(0,"127.0.0.1",resolve));
    const endpoint="http://127.0.0.1:"+(server.address() as import("net").AddressInfo).port;
    try{
      // A served tool call records exactly one success observation.
      const ok=await fetch(endpoint+"/mcp",{method:"POST",
        headers:headers("tools/call","get_service_status"),
        body:payload("tools/call",{name:"get_service_status",arguments:{}})});
      assert.equal(ok.status,200);
      // A refused call is recorded as error: the tool refuses the malformed
      // arguments with isError, no tool executes and nothing is invented.
      const bad=await fetch(endpoint+"/mcp",{method:"POST",
        headers:headers("tools/call","get_project"),
        body:payload("tools/call",{name:"get_project",arguments:{project_id:"nope"}})});
      assert.equal(bad.status,200);
      const badBody=await bad.json() as Record<string,any>;
      assert.equal(badBody.result?.isError,true,
        "expected a tool-level validation refusal");
      // An unknown tool is a JSON-RPC protocol error: the observed outcome is
      // "denied" and nothing executes.
      const unknown=await fetch(endpoint+"/mcp",{method:"POST",
        headers:headers("tools/call","not_a_real_tool"),
        body:payload("tools/call",{name:"not_a_real_tool",arguments:{}})});
      assert.equal(unknown.status,200);
      const unknownBody=await unknown.json() as Record<string,any>;
      assert.ok("error" in unknownBody,"expected a JSON-RPC refusal");
      // Non-tool traffic never appears in telemetry.
      await fetch(endpoint+"/mcp",{method:"POST",
        headers:headers("tools/list"),body:payload("tools/list")});
      await fetch(endpoint+"/mcp",{method:"POST",body:"{}",
        headers:{"Content-Type":"application/json"}});
      // Recording is asynchronous but bounded; the small insert completes
      // before the response round-trip returns in practice. Confirm via a
      // short settled read.
      await new Promise(resolve=>setTimeout(resolve,150));
      const summary=await usage.summary("user-a");
      assert.ok(summary,"telemetry must exist for the served account");
      assert.equal(summary.totalCalls,3);
      assert.deepEqual([...summary.byTool].sort((a,b)=>a.tool.localeCompare(b.tool))
        .map(t=>t.tool),["get_project","get_service_status","not_a_real_tool"]);
      assert.deepEqual([...summary.byStatus].sort((a,b)=>a.status.localeCompare(b.status))
        .map(s=>s.status),["denied","error","success"]);
      assert.deepEqual(summary.byClient.map(c=>c.clientId),["test-client"]);
      // No other owner, client or fabricated tool appears.
      assert.equal(await usage.summary("user-b"),null);
      const recent=await usage.recent("user-a");
      assert.equal(recent.length,3);
      for(const event of recent){
        assert.ok(["get_service_status","get_project","not_a_real_tool"]
          .includes(event.tool));
        assert.deepEqual(Object.keys(event).sort(),
          ["at","clientId","id","status","tool"]);
      }
    }finally{
      await new Promise<void>(resolve=>server.close(()=>resolve()));
    }
  });
});
