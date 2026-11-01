import assert from "node:assert/strict";
import {randomUUID} from "node:crypto";
import type {PreparedOwnerSummary} from "../src/connector-ws.js";
import type {TrustedOAuthReadIdentity} from "../src/connector-read-gate.js";
import { createServer as httpCreateServer, request as httpRequest, type Server } from "node:http";
import { after, before, test } from "node:test";
import type { AddressInfo } from "node:net";
import { createHttpServer } from "../src/http.js";
import type { Config } from "../src/config.js";
import type { Inventory, Device, Project } from "../src/store.js";
import type { Actor, Verifier } from "../src/auth.js";
import type { GrantManagement } from "../src/grants.js";

const id = "3fa85f64-5717-4562-b3fc-2c963f66afa6";
const mockProject: Project = {
  id, alias: "USB-C Controller", deviceId: "d108b5f4-22f2-4b3c-b62d-55163fa34814",
  enabled: true, maxMode: "readonly", available: false,
  reason: "remote_connector_not_implemented"
};
let accessAllowed = true;
const inventory: Inventory = {
  async isAccessTokenAllowed(){return accessAllowed;},
  async listDevices(owner,clientId): Promise<Device[]> {
    return owner === "user-a" && clientId === "test-client"
      ? [{id:mockProject.deviceId, alias:"Workstation", enabled:true, lastSeenAt:null, connected:false}]
      : [];
  },
  async listProjects(owner, clientId) { return owner === "user-a" && clientId === "test-client" ? [mockProject] : []; },
  async getProject(owner, clientId, projectId) { return owner === "user-a" && clientId === "test-client" && projectId === id ? mockProject : null; }
};
const managementCalls: unknown[] = [];
const grants: GrantManagement = {
  async revokeClient(owner,client) {
    managementCalls.push({owner,client,action:"revoke"});
    return owner==="user-a" ? 1 : 0;
  },
  async setGrant(owner, client, project, policy) {
    managementCalls.push({owner,client,project,policy});
    if (owner !== "user-a") return false;
    if (policy.maxMode === "write") throw new Error("POLICY_EXCEEDS_PROJECT");
    return project === id;
  }
};
// The synthetic JWT is the same token for both prepare and completion.
// Its issuance time must not change when CI crosses a wall-clock second.
const fixtureTokenIssuedAt=Math.floor(Date.now()/1000);
const verify: Verifier = async token => {
  if (!["test-user-a","test-user-b","admin-user-a","rogue-admin"].includes(token)) throw new Error("invalid");
  const actor: Actor = {
    sub: token === "test-user-b" ? "user-b" : "user-a",
    clientId: token === "admin-user-a" ? "portal-client" : token === "rogue-admin" ? "other-client" : "test-client",
    scopes: new Set(["projects:read", ...(["admin-user-a","rogue-admin"].includes(token) ? ["projects:manage"] : [])]),
    issuedAt: fixtureTokenIssuedAt
  };
  return actor;
};
const config: Config = {
  host:"127.0.0.1", port:0, publicOrigin:"http://127.0.0.1",
  issuer:"https://issuer.example", jwksUrl:"https://issuer.example/keys",
  audience:"http://127.0.0.1/mcp", databaseUrl:"unused", allowedOrigins:[], managementClientId:"portal-client"
};
let server: Server;
let endpoint: string;
before(async () => {
  server = createHttpServer(config, inventory, verify, {grants:grants});
  await new Promise<void>(resolve => server.listen(0, "127.0.0.1", resolve));
  endpoint = "http://127.0.0.1:" + (server.address() as AddressInfo).port;
});
after(async () => { await new Promise<void>(resolve => server.close(() => resolve())); });
const headers = (token = "test-user-a", method?:string, name?:string) => ({
  "Authorization": "Bearer " + token,
  "Content-Type": "application/json",
  "Accept": "application/json, text/event-stream",
  "MCP-Protocol-Version": "2026-07-28",
  ...(method ? {"Mcp-Method":method} : {}),
  ...(name ? {"Mcp-Name":name} : {})
});
function payload(method:string, params:object={}) {
  return JSON.stringify({jsonrpc:"2.0", id:1, method, params: {
    ...params, _meta:{"io.modelcontextprotocol/clientInfo":{name:"security-test",version:"1.0.0"},"io.modelcontextprotocol/protocolVersion":"2026-07-28","io.modelcontextprotocol/clientCapabilities":{}}
  }});
}
async function call(method:string, params:object={}, token = "test-user-a", toolName?:string) {
  const res = await fetch(endpoint+"/mcp", {
    method:"POST", headers:headers(token,method,toolName),
    body:payload(method,params)
  });
  return { status:res.status, data:await res.json() as Record<string,any> };
}
test("public health and OAuth resource discovery are metadata-only", async () => {
  const health = await fetch(endpoint+"/health");
  assert.equal(health.status, 200);
  assert.equal((await health.json()).remoteConnector, "not_implemented");
  const meta = await fetch(endpoint+"/.well-known/oauth-protected-resource");
  assert.equal((await meta.json()).resource, config.audience);
  const nested = await fetch(endpoint+"/.well-known/oauth-protected-resource/mcp");
  assert.equal((await nested.json()).resource, config.audience);
});
test("MCP denies anonymous and invalid bearer traffic before tool discovery", async () => {
  const anon = await fetch(endpoint+"/mcp", {method:"POST",body:payload("tools/list"),headers:{"Content-Type":"application/json"}});
  assert.equal(anon.status,401);
  assert.match(anon.headers.get("www-authenticate")??"",/oauth-protected-resource/);
  const wrong = await call("tools/list",{},"invalid");
  assert.equal(wrong.status,401);
});
test("MCP tools/list advertises only bounded Cloud inventory tools", async () => {
  const out = await call("tools/list");
  assert.equal(out.status,200,JSON.stringify(out.data));
  const names=(out.data.result?.tools??[]).map((t:{name:string})=>t.name);
  assert.deepEqual(names.sort(), ["discover_project_workflow","get_project","get_service_status","list_devices","list_projects"]);
  assert.equal(names.includes("pcb_delete_items"), false);
});
test("task discovery reports only enabled, granted Cloud operations",async()=>{
  const inspect=async(token:string,task:string,projectId?:string)=>{
    const args={task,...(projectId?{project_id:projectId}:{})};
    const response=await call("tools/call",{
      name:"discover_project_workflow",arguments:args
    },token,"discover_project_workflow");
    assert.equal(response.status,200);
    return response.data.result.structuredContent as Record<string,unknown>;
  };
  // The default Cloud instance only lists metadata. No native operations
  // may appear in task discovery if the corresponding reader is not enabled.
  for(const task of ["inspect_engine","check_board_drc","check_project_files"]){
    const disabled=await inspect("test-user-a",task,id);
    assert.equal(disabled.available,false);
    assert.equal(disabled.reason,"cloud_operation_not_enabled");
    assert.deepEqual(disabled.tools,[]);
  }
  const foreign=await inspect("test-user-b","inspect_engine",id);
  assert.deepEqual(foreign,{available:false,selectionRequired:false,tools:[]});
  const unknown=await inspect("test-user-a","inspect_engine",randomUUID());
  assert.deepEqual(unknown,{available:false,selectionRequired:false,tools:[]});
  const invalid=await call("tools/call",{
    name:"discover_project_workflow",arguments:{task:"edit_pcb",project_id:id}
  },"test-user-a","discover_project_workflow");
  assert.equal(invalid.status,200);
  assert.match(JSON.stringify(invalid.data),/isError|invalid/i);
});

test("task discovery respects enabled operation and ambiguous project selection",async()=>{
  const another:Project={...mockProject,id:randomUUID(),alias:"Second board"};
  const scoped:Inventory={
    ...inventory,
    async listProjects(owner,client){
      return owner==="user-a"&&client==="test-client"?[mockProject,another]:[];
    },
    async getProject(owner,client,projectId){
      return owner==="user-a"&&client==="test-client"?
        [mockProject,another].find(p=>p.id===projectId)??null:null;
    }
  };
  const proxy=createHttpServer(config,scoped,verify,{
    mcpProjectInspectionEnabled:true,
    summaryRelay:()=>({
      prepareOwnerInspection:()=>null,
      requestInspection:async()=>null,
      prepareOwnerSummary:()=>null,
      requestSummary:async()=>null
    })
  });
  await new Promise<void>(done=>proxy.listen(0,"127.0.0.1",done));
  const origin="http://127.0.0.1:"+(proxy.address() as AddressInfo).port;
  async function discover(args:object,token="test-user-a"){
    const reply=await fetch(origin+"/mcp",{
      method:"POST",headers:headers(token,"tools/call","discover_project_workflow"),
      body:payload("tools/call",{name:"discover_project_workflow",arguments:args})
    });
    assert.equal(reply.status,200);
    return ((await reply.json()) as any).result.structuredContent;
  }
  try{
    const ambiguous=await discover({task:"inspect_engine"});
    assert.deepEqual(ambiguous,{
      available:false,selectionRequired:true,tools:[]
    });
    assert.deepEqual(await discover({task:"inspect_engine",project_id:another.id}),{
      available:true,selectionRequired:false,
      tools:["get_project_engine_status"],requiresOwnerSession:true
    });
    const drc=await discover({task:"check_board_drc",project_id:another.id});
    assert.equal(drc.available,false);
    assert.deepEqual(drc.tools,[]);
    assert.equal(drc.reason,"cloud_operation_not_enabled");
    const foreign=await discover({task:"inspect_engine",project_id:another.id},"test-user-b");
    assert.equal(foreign.available,false);
    assert.deepEqual(foreign.tools,[]);
  }finally{
    await new Promise<void>(done=>proxy.close(()=>done()));
  }
});

test("MCP calls are owner scoped; other users cannot discover projects", async () => {
  const a = await call("tools/call",{name:"list_projects",arguments:{}},"test-user-a","list_projects");
  assert.equal(a.status,200,JSON.stringify(a.data));
  assert.match(JSON.stringify(a.data),/USB-C Controller/);
  const b = await call("tools/call",{name:"list_projects",arguments:{}},"test-user-b","list_projects");
  assert.equal(b.status,200,JSON.stringify(b.data));
  assert.doesNotMatch(JSON.stringify(b.data),/USB-C Controller/);
  const foreign = await call("tools/call",{name:"get_project",arguments:{project_id:id}},"test-user-b","get_project");
  assert.equal(foreign.status,200,JSON.stringify(foreign.data));
  assert.doesNotMatch(JSON.stringify(foreign.data),/USB-C Controller/);
});
test("rejects untrusted browser Origin and oversized messages", async () => {
  const origin = await fetch(endpoint+"/mcp",{method:"POST",headers:{Origin:"https://attacker.example"},body:"{}"});
  assert.equal(origin.status,403);
  const large = await fetch(endpoint+"/mcp",{method:"POST",headers:headers(),body:" ".repeat(1048577)});
  assert.equal(large.status,413);
});
test("unknown URLs are not an enrollment API",async()=>{
  const r=await fetch(endpoint+"/api/devices",{method:"POST",headers:headers(),body:"{}"});
  assert.equal(r.status,404);
});


test("project grant endpoint requires first-party OAuth client and admin scope",async()=>{
  const path="/api/v1/projects/"+id+"/grants";
  const body=JSON.stringify({clientId:"claude-mcp-client",enabled:true,maxMode:"readonly"});
  async function send(token:string, value=body) {
    const result=await fetch(endpoint+path,{method:"PUT",headers:headers(token),body:value});
    return result.status;
  }
  assert.equal(await send("invalid"),401);
  assert.equal(await send("test-user-a"),403);
  assert.equal(await send("rogue-admin"),403);
  assert.equal(await send("admin-user-a",JSON.stringify({clientId:"client",enabled:true,maxMode:"readonly",localPath:"C:/Secrets"})),400);
  assert.equal(await send("admin-user-a",JSON.stringify({clientId:"client",enabled:true,maxMode:"write"})),409);
  assert.equal(await send("admin-user-a"),200);
  assert.deepEqual(managementCalls.at(-1),{
    owner:"user-a",client:"portal-client",project:id,
    policy:{clientId:"claude-mcp-client",enabled:true,maxMode:"readonly"}
  });
  const foreign=await fetch(endpoint+"/api/v1/projects/8a1dcd04-15d1-4354-86f5-2918b4a8b2e9/grants",{
    method:"PUT",headers:headers("admin-user-a"),body
  });
  assert.equal(foreign.status,404);
});


test("identity routes are proxied only when enabled, preserving response cookies",async()=>{
  const mockIdentity = {
    handler: async (request: Request) => {
      assert.equal(new URL(request.url).origin,config.publicOrigin);
      return new Response(JSON.stringify({authenticated:false}),{
        status:200,
        headers:{"content-type":"application/json","set-cookie":"state=opaque; Path=/; HttpOnly; SameSite=Lax"}
      });
    }
  };
  const proxy=createHttpServer(config, inventory, verify, {grants:grants, identity:mockIdentity});
  await new Promise<void>(resolve=>proxy.listen(0,"127.0.0.1",resolve));
  const port=(proxy.address() as AddressInfo).port;
  try {
    const base="http://127.0.0.1:"+port;
    const discovery=await fetch(base+"/.well-known/oauth-authorization-server/api/auth");
    assert.equal(discovery.status,200);
    assert.match(discovery.headers.get("set-cookie")??"",/HttpOnly/);
    // Untrusted/opaque Origin on public GET navigation is harmless; the
    // browser must still complete the same-origin POST with CSRF checks.
    const navigation=await fetch(base+"/auth/start/github",{
      headers:{Origin:"null"},redirect:"manual"
    });
    assert.equal(navigation.status,303);
    assert.equal(navigation.headers.get("location"),"/sign-in");
    const publicSignIn=await fetch(base+"/sign-in",{headers:{Origin:"chrome-extension://fixture"}});
    assert.equal(publicSignIn.status,200);
    assert.match(await publicSignIn.text(),/Continue with GitHub/);
    const maliciousPost=await fetch(base+"/auth/start/github",{
      method:"POST",headers:{Origin:"null","Content-Type":"application/x-www-form-urlencoded"},
      body:"oauth_query=",redirect:"manual"
    });
    assert.equal(maliciousPost.status,403);
    const protectedRoute=await fetch(base+"/api/auth/jwks",{headers:{Origin:"null"}});
    assert.equal(protectedRoute.status,403);
    // Raw HTTP is needed: undici's fetch overrides the supplied Host header.
    const forgedHostStatus=await new Promise<number>((resolve,reject)=>{
      const req=httpRequest({hostname:"127.0.0.1",port,path:"/auth/start/github",
        headers:{Host:"forged.invalid",Origin:"null"}},response=>{
        response.resume();response.on("end",()=>resolve(response.statusCode??0));
      });
      req.on("error",reject);req.end();
    });
    assert.equal(forgedHostStatus,403);
    const keys=await fetch(base+"/api/auth/jwks");
    assert.equal(keys.status,200);
    assert.deepEqual(await keys.json(),{authenticated:false});
  } finally {
    await new Promise<void>(resolve=>proxy.close(()=>resolve()));
  }
});

test("consent URL is unreachable when built-in identity is disabled",async()=>{
  const response=await fetch(endpoint+"/consent?client_id=unknown");
  assert.equal(response.status,404);
});
test("HTTP consent rejects forged unsigned request even if identity is configured",async()=>{
  const mockIdentity={
    handler:async (_request:Request)=>Response.json({client_id:"unknown",client_name:"Unknown"}),
    $context:Promise.resolve({secret:"test-auth-secret-for-consent"}),
    api:{getSession:async()=>({user:{id:"test-user"}})}
  };
  const proxy=createHttpServer(config, inventory, verify, {grants:grants, identity:mockIdentity as never});
  await new Promise<void>(resolve=>proxy.listen(0,"127.0.0.1",resolve));
  const port=(proxy.address() as AddressInfo).port;
  try{
    const response=await fetch("http://127.0.0.1:"+port+"/consent?client_id=unknown&scope=projects%3Aread");
    assert.equal(response.status,403);
    assert.doesNotMatch(await response.text(),/Approve<\/button>/);
  }finally{
    await new Promise<void>(resolve=>proxy.close(()=>resolve()));
  }
});

test("connection management is fail-closed without built-in identity",async()=>{
  assert.equal((await fetch(endpoint+"/connections")).status,404);
  const response=await fetch(endpoint+"/connections/revoke",{method:"POST",headers:{"Origin":config.publicOrigin,
    "Content-Type":"application/x-www-form-urlencoded"},body:"id=anything"});
  assert.equal(response.status,404);
});
test("HTTP connection list requires signed-in session",async()=>{
  const mockIdentity={
    handler:async()=>Response.json({client_id:"test"}),
    api:{getSession:async()=>null},
    $context:Promise.resolve({secret:"test-only-not-a-production-secret"})
  };
  const proxy=createHttpServer(config, inventory, verify, {grants:grants, identity:mockIdentity as never});
  await new Promise<void>(resolve=>proxy.listen(0,"127.0.0.1",resolve));
  try {
    const port=(proxy.address() as AddressInfo).port;
    const res=await fetch("http://127.0.0.1:"+port+"/connections",{redirect:"manual"});
    assert.equal(res.status,303);
    assert.equal(res.headers.get("location"),"/sign-in");
  } finally {
    await new Promise<void>(resolve=>proxy.close(()=>resolve()));
  }
});


test("a revoked signed JWT is rejected at MCP and management edges",async()=>{
  accessAllowed=false;
  try {
    const mcp=await fetch(endpoint+"/mcp",{
      method:"POST",
      headers:headers("test-user-a"),
      body:JSON.stringify({jsonrpc:"2.0",id:731,method:"tools/list",params:{}})
    });
    assert.equal(mcp.status,401);
    assert.equal((await mcp.json()).error,"revoked_access_token");
    const grant=await fetch(endpoint+"/api/v1/projects/"+id+"/grants",{
      method:"PUT",headers:headers("admin-user-a"),
      body:JSON.stringify({clientId:"test-client",enabled:true,maxMode:"readonly"})
    });
    assert.equal(grant.status,401);
    assert.equal((await grant.json()).error,"revoked_access_token");
  } finally {
    accessAllowed=true;
  }
});

test("premium public interface and same-origin stylesheet use hardened headers",async()=>{
  const landing=await fetch(endpoint+"/");
  assert.equal(landing.status,200);
  assert.match(landing.headers.get("content-type")??"",/text\/html/);
  assert.match(landing.headers.get("content-security-policy")??"",/style-src 'self'/);
  const body=await landing.text();
  assert.match(body,/KiCad MCP Cloud/);
  assert.match(body,/Account access pending/);
  assert.doesNotMatch(body,/href="\/sign-in"/);
  const style=await fetch(endpoint+"/assets/ui.css");
  assert.equal(style.status,200);
  assert.match(style.headers.get("content-type")??"",/text\/css/);
  assert.match(await style.text(),/\.landing-panel/);
  assert.equal((await fetch(endpoint+"/assets/ui.js")).status,404);
});

function testPrepared(
  actor:TrustedOAuthReadIdentity,deviceId:string,projectId:string
):PreparedOwnerSummary{
  return Object.freeze({
    requestId:randomUUID(),ownerSub:actor.ownerSub,clientId:actor.clientId,
    deviceId,projectId,origin:config.publicOrigin,
    operation:"project_summary",expiresAtUnixMs:Date.now()+30_000
  });
}
const summaryPath="/api/v1/connector/project-summary";
const testIntentDelivery=async(scope:PreparedOwnerSummary)=>(
  "https://owner.example.test/owner-read/review?requestId="+scope.requestId
);
async function postLoopbackSummary(
  origin:string,route:"prepare"|"complete",bearer:string,body:string
):Promise<Response>{
  const address=new URL(origin);
  if(address.protocol!=="http:"||address.hostname!=="127.0.0.1"||
     !/^[0-9]{1,5}$/.test(address.port))
    throw Error("Only the local fixture server is supported");
  const path=route==="prepare"?summaryPath+"/prepare":summaryPath;
  return new Promise<Response>((resolve,reject)=>{
    const request=httpRequest({
      hostname:"127.0.0.1",port:Number(address.port),path,
      method:"POST",headers:headers(bearer)
    },reply=>{
      const chunks:Buffer[]=[];
      reply.on("data",(part:Buffer)=>chunks.push(Buffer.from(part)));
      reply.on("end",()=>resolve(new Response(Buffer.concat(chunks),{
        status:reply.statusCode??500
      })));
      reply.on("error",reject);
    });
    request.on("error",reject);
    request.end(body);
  });
}
async function prepareHttpRead(origin:string,bearer:string,body:string){
  return postLoopbackSummary(origin,"prepare",bearer,body);
}
async function completeHttpRead(origin:string,bearer:string,
  deviceId:string,projectId:string,requestId:string){
  return postLoopbackSummary(origin,"complete",bearer,
    JSON.stringify({deviceId,projectId,requestId}));
}
async function twoStepHttpRead(origin:string,token:string,
  deviceId:string,projectId:string):Promise<Response>{
  const ready=await prepareHttpRead(origin,token,JSON.stringify({deviceId,projectId}));
  if(!ready.ok)return ready;
  const scope=await ready.json() as {requestId:string};
  return completeHttpRead(origin,token,deviceId,projectId,scope.requestId);
}

test("Cloud HTTP read refuses grant revocation after relay result but before reply",async()=>{
  const path="/api/v1/connector/project-summary";
  let grantActive=true;
  let lookedUp=0;
  const boundedInventory:Inventory={
    ...inventory,
    async getProject(owner,clientId,projectId){
      lookedUp++;
      if(!grantActive)return null;
      return inventory.getProject(owner,clientId,projectId);
    }
  };
  const relay={
    prepareOwnerSummary:testPrepared,
    async requestSummary(_actor:unknown,_device:string,projectId:string,
      prepared:PreparedOwnerSummary){
      // Simulates a real owner revocation in the interleaving between the
      // WSS relay's acceptance and the HTTP response write.
      grantActive=false;
      return {kind:"connector.local_read_preview" as const,version:1 as const,
        requestId:prepared.requestId,projectId,operation:"project_summary" as const,
        files:{projectPresent:true,boardPresent:false,schematicPresent:false}};
    }
  };
  const proxy=createHttpServer(config,boundedInventory,verify,{summaryRelay:()=>relay,ownerIntentDelivery:testIntentDelivery});
  await new Promise<void>(resolve=>proxy.listen(0,"127.0.0.1",resolve));
  try{
    const port=(proxy.address() as AddressInfo).port;
    const result=await twoStepHttpRead("http://127.0.0.1:"+port,
      "test-user-a",mockProject.deviceId,id);
    assert.equal(result.status,403,
      "Revoke-after-relay must not return project presence bytes to the client");
    assert.equal(lookedUp,2);
    assert.deepEqual(await result.json(),{error:"forbidden"});
  }finally{
    await new Promise<void>(resolve=>proxy.close(()=>resolve()));
  }
});

test("Cloud HTTP read denies token expiry during the final awaited project lookup",async()=>{
  const path="/api/v1/connector/project-summary";
  let expired=false;
  let verifications=0;
  let lookups=0;
  const expiryVerifier:Verifier=async token=>{
    verifications++;
    if(expired)throw Error("synthetic access token expired");
    return verify(token);
  };
  const delayedInventory:Inventory={
    ...inventory,
    async getProject(owner,clientId,projectId){
      lookups++;
      const found=await inventory.getProject(owner,clientId,projectId);
      // Simulate a JWT expiry exactly while the final project/grant
      // lookup was awaited, after the first post-relay JWT verification.
      if(lookups===2)expired=true;
      return found;
    }
  };
  const relay={
    prepareOwnerSummary:testPrepared,
    async requestSummary(_actor:unknown,_device:string,projectId:string,
      prepared:PreparedOwnerSummary){
      return {kind:"connector.local_read_preview" as const,version:1 as const,
        requestId:prepared.requestId,projectId,operation:"project_summary" as const,
        files:{projectPresent:true,boardPresent:false,schematicPresent:false}};
    }
  };
  const proxy=createHttpServer(config,delayedInventory,expiryVerifier,{summaryRelay:()=>relay,ownerIntentDelivery:testIntentDelivery});
  await new Promise<void>(resolve=>proxy.listen(0,"127.0.0.1",resolve));
  try{
    const port=(proxy.address() as AddressInfo).port;
    const result=await twoStepHttpRead("http://127.0.0.1:"+port,
      "test-user-a",mockProject.deviceId,id);
    assert.equal(result.status,403,
      "Token expired during final grant lookup must never release project presence");
    assert.deepEqual(await result.json(),{error:"forbidden"});
    assert.equal(lookups,2);
    assert.equal(verifications,5,
      "HTTP must verify JWT immediately before delivering the final metadata");
  }finally{
    await new Promise<void>(resolve=>proxy.close(()=>resolve()));
  }
});

test("Cloud HTTP read denies token revocation during the final project lookup",async()=>{
  let tokenActive=true;
  let cutoffChecks=0;
  let projectChecks=0;
  const boundedInventory:Inventory={
    ...inventory,
    async isAccessTokenAllowed(){
      cutoffChecks++;
      return tokenActive;
    },
    async getProject(owner,clientId,projectId){
      projectChecks++;
      const project=await inventory.getProject(owner,clientId,projectId);
      // Model revocation committed while the last project query awaited
      // the database, after the previous cutoff check succeeded.
      if(projectChecks===2)tokenActive=false;
      return project;
    }
  };
  const relay={
    prepareOwnerSummary:testPrepared,
    async requestSummary(_actor:unknown,_device:string,projectId:string,
      prepared:PreparedOwnerSummary){
      return {kind:"connector.local_read_preview" as const,version:1 as const,
        requestId:prepared.requestId,projectId,operation:"project_summary" as const,
        files:{projectPresent:true,boardPresent:false,schematicPresent:false}};
    }
  };
  const proxy=createHttpServer(config,boundedInventory,verify,{summaryRelay:()=>relay,ownerIntentDelivery:testIntentDelivery});
  await new Promise<void>(resolve=>proxy.listen(0,"127.0.0.1",resolve));
  try{
    const port=(proxy.address() as AddressInfo).port;
    const result=await twoStepHttpRead("http://127.0.0.1:"+port,
      "test-user-a",mockProject.deviceId,id);
    assert.equal(result.status,403,
      "revocation completed during final project lookup must deny presence data");
    assert.deepEqual(await result.json(),{error:"forbidden"});
    assert.equal(projectChecks,2);
    assert.equal(cutoffChecks,5,
      "final project lookup must be followed by a new cutoff check");
  }finally{
    await new Promise<void>(resolve=>proxy.close(()=>resolve()));
  }
});

test("Cloud read route is absent without connector and validates OAuth and payload when attached",async()=>{
  const path="/api/v1/connector/project-summary";
  const validBody=JSON.stringify({deviceId:mockProject.deviceId,projectId:id});
  const absent=await fetch(endpoint+path,{method:"POST",headers:headers(),body:validBody});
  assert.equal(absent.status,404);
  const calls:unknown[]=[];
  const mockRelay={
    prepareOwnerSummary:testPrepared,
    async requestSummary(actor:unknown,deviceId:string,projectId:string,
      prepared:PreparedOwnerSummary){
      calls.push({actor,deviceId,projectId,prepared});
      return {kind:"connector.local_read_preview" as const,version:1 as const,
        requestId:prepared.requestId,projectId,operation:"project_summary" as const,
        files:{projectPresent:true,boardPresent:false,schematicPresent:false}};
    }
  };
  const proxy=createHttpServer(config, inventory, verify, {grants:grants, summaryRelay:()=>mockRelay,ownerIntentDelivery:testIntentDelivery});
  await new Promise<void>(resolve=>proxy.listen(0,"127.0.0.1",resolve));
  const origin="http://127.0.0.1:"+(proxy.address() as AddressInfo).port;
  try{
    const send=(token:string,body=validBody)=>prepareHttpRead(origin,token,body);
    assert.equal((await send("invalid")).status,401);
    assert.equal((await send("test-user-b",JSON.stringify({deviceId:"bad",projectId:id}))).status,400);
    assert.equal((await send("test-user-a",JSON.stringify({deviceId:mockProject.deviceId,
      projectId:id,operation:"run_drc"}))).status,400);
    assert.equal(calls.length,0);
    accessAllowed=false;
    assert.equal((await send("test-user-a")).status,403);
    accessAllowed=true;
    const ready=await send("test-user-a");
    assert.equal(ready.status,200);
    const scope=await ready.json() as PreparedOwnerSummary;
    assert.equal(scope.ownerSub,"user-a");
    assert.equal(scope.clientId,"test-client");
    assert.equal(scope.deviceId,mockProject.deviceId);
    assert.equal(scope.projectId,id);
    assert.equal(calls.length,0,"Preparing never reads from the device");
    const accepted=await completeHttpRead(origin,"test-user-a",
      mockProject.deviceId,id,scope.requestId);
    assert.equal(accepted.status,200);
    assert.equal((await accepted.json() as {files:{projectPresent:boolean}})
      .files.projectPresent,true);
    assert.equal(calls.length,1);
    assert.equal((calls[0] as {prepared:PreparedOwnerSummary}).prepared.requestId,
      scope.requestId);
    assert.equal((await completeHttpRead(origin,"test-user-a",
      mockProject.deviceId,id,scope.requestId)).status,404,
      "A completed HTTP intent cannot be replayed");
    assert.equal((await fetch(origin+path,{method:"POST",headers:headers(),
      body:validBody})).status,400,
      "Old immediate read format must be rejected");
    // Even a buggy relay must not authorize a different device merely
    // because the client has a grant for this project.
    const wrongDevice=await send("test-user-a",JSON.stringify({
      deviceId:"11111111-1111-4111-8111-111111111111",projectId:id
    }));
    assert.equal(wrongDevice.status,403);
    assert.deepEqual(await wrongDevice.json(),{error:"forbidden"});
  }finally{
    accessAllowed=true;
    await new Promise<void>(resolve=>proxy.close(()=>resolve()));
  }
});


test("prepared HTTP request is token-bound, single-use, scope-bound and not a bearer grant",async()=>{
  const observed:string[]=[];
  const relay={
    prepareOwnerSummary:testPrepared,
    async requestSummary(_actor:TrustedOAuthReadIdentity,_device:string,
      projectId:string,prepared:PreparedOwnerSummary){
      observed.push(prepared.requestId);
      return {kind:"connector.local_read_preview" as const,version:1 as const,
        requestId:prepared.requestId,projectId,operation:"project_summary" as const,
        files:{projectPresent:true,boardPresent:false,schematicPresent:false}};
    }
  };
  const verifier:Verifier=token=>token==="alternate-signed-token"
    ? verify("test-user-a") : verify(token);
  const proxy=createHttpServer(config,inventory,verifier,{summaryRelay:()=>relay,ownerIntentDelivery:testIntentDelivery});
  await new Promise<void>(resolve=>proxy.listen(0,"127.0.0.1",resolve));
  const origin="http://127.0.0.1:"+(proxy.address() as AddressInfo).port;
  const start=async()=>{
    const response=await prepareHttpRead(origin,"test-user-a",
      JSON.stringify({deviceId:mockProject.deviceId,projectId:id}));
    assert.equal(response.status,200);
    return response.json() as Promise<PreparedOwnerSummary>;
  };
  try{
    const intent=await start();
    assert.equal(observed.length,0,"Preparation cannot read device metadata");
    assert.equal((await completeHttpRead(origin,"admin-user-a",
      mockProject.deviceId,id,intent.requestId)).status,404,
      "Different OAuth client cannot complete another client's request");
    assert.equal((await completeHttpRead(origin,"test-user-a",
      mockProject.deviceId,id,intent.requestId)).status,404,
      "A mismatched completion burns the one-use request");
    assert.equal(observed.length,0);

    const otherToken=await start();
    assert.equal((await completeHttpRead(origin,"alternate-signed-token",
      mockProject.deviceId,id,otherToken.requestId)).status,404,
      "A different bearer token for the same owner/client cannot spend an intent");
    assert.equal((await completeHttpRead(origin,"test-user-a",
      mockProject.deviceId,id,otherToken.requestId)).status,404,
      "A token-substitution attempt consumes the prepared reference");

    const other=await start();
    assert.equal((await completeHttpRead(origin,"test-user-a",
      randomUUID(),id,other.requestId)).status,404,
      "One approval cannot be redirected to another device");
    assert.equal((await completeHttpRead(origin,"test-user-a",
      mockProject.deviceId,id,other.requestId)).status,404);

    const third=await start();
    assert.equal((await completeHttpRead(origin,"test-user-a",
      mockProject.deviceId,randomUUID(),third.requestId)).status,404,
      "One approval cannot be redirected to another project");
    assert.equal((await completeHttpRead(origin,"test-user-a",
      mockProject.deviceId,id,third.requestId)).status,404);

    const concurrent=await start();
    const results=await Promise.all([
      completeHttpRead(origin,"test-user-a",mockProject.deviceId,id,
        concurrent.requestId),
      completeHttpRead(origin,"test-user-a",mockProject.deviceId,id,
        concurrent.requestId)
    ]);
    assert.deepEqual(results.map(x=>x.status).sort(),[200,404]);
    assert.deepEqual(observed,[concurrent.requestId]);
    assert.equal((await completeHttpRead(origin,"test-user-a",
      mockProject.deviceId,id,concurrent.requestId)).status,404);

    const noPreparation=await fetch(origin+summaryPath,{
      method:"POST",headers:headers(),
      body:JSON.stringify({deviceId:mockProject.deviceId,projectId:id})
    });
    assert.equal(noPreparation.status,400,
      "Legacy direct read payload cannot dispatch a connector request");
  }finally{
    await new Promise<void>(r=>proxy.close(()=>r()));
  }
});


test("Cloud prepared HTTP read fails closed without authenticated owner delivery",async()=>{
  let reads=0;
  const relay={
    prepareOwnerSummary:testPrepared,
    async requestSummary(){
      reads++;
      return null;
    }
  };
  const noDelivery=createHttpServer(config,inventory,verify,{
    summaryRelay:()=>relay
  });
  const deniedDelivery=createHttpServer(config,inventory,verify,{
    summaryRelay:()=>relay,
    ownerIntentDelivery:async()=>null
  });
  try{
    for(const proxy of [noDelivery,deniedDelivery]){
      await new Promise<void>(done=>proxy.listen(0,"127.0.0.1",done));
      const endpoint="http://127.0.0.1:"+
        (proxy.address() as AddressInfo).port;
      const attempt=await prepareHttpRead(endpoint,"test-user-a",
        JSON.stringify({deviceId:mockProject.deviceId,projectId:id}));
      assert.equal(attempt.status,404,
        "Client cannot obtain a preparatory request without trusted issuer delivery");
      assert.equal(reads,0);
    }
  }finally{
    for(const proxy of [noDelivery,deniedDelivery]){
      if(proxy.listening)await new Promise<void>(done=>proxy.close(()=>done()));
    }
  }
});

// The no-customer pilot uses an existing owner grant and an explicitly
// launched local one-shot process. No independent WebAuthn claim is made.
test("MCP one-shot presence pilot denies foreign and revoked project access",async()=>{
  let reads=0,grantActive=true,revokeDuringRead=false;
  const scoped:Inventory={
    ...inventory,
    async getProject(owner,clientId,projectId){
      if(!grantActive)return null;
      return inventory.getProject(owner,clientId,projectId);
    }
  };
  const relay={
    prepareOwnerSummary:testPrepared,
    async requestSummary(_oauth:unknown,_deviceId:string,projectId:string,
      prepared:PreparedOwnerSummary){
      reads++;
      if(revokeDuringRead)grantActive=false;
      return {kind:"connector.local_read_preview" as const,version:1 as const,
        requestId:prepared.requestId,projectId,operation:"project_summary" as const,
        files:{projectPresent:true,boardPresent:true,schematicPresent:false}};
    }
  };
  const proxy=createHttpServer(config,scoped,verify,{
    summaryRelay:()=>relay,mcpProjectPresenceEnabled:true
  });
  await new Promise<void>(resolve=>proxy.listen(0,"127.0.0.1",resolve));
  const origin="http://127.0.0.1:"+(proxy.address() as AddressInfo).port;
  const invoke=async(method:string,params:object,token="test-user-a",name?:string)=>{
    const response=await fetch(origin+"/mcp",{
      method:"POST",headers:headers(token,method,name),body:payload(method,params)
    });
    return {status:response.status,data:await response.json() as Record<string,any>};
  };
  try{
    const health=await fetch(origin+"/health");
    assert.equal((await health.json()).remoteConnector,"operator_one_shot_presence");
    const tools=await invoke("tools/list",{});
    assert.equal(tools.status,200);
    const all=(tools.data.result?.tools??[]).map((t:{name:string})=>t.name);
    assert.ok(all.includes("get_project_presence"));
    assert.equal(all.some((n:string)=>/run_drc|run_erc|write|delete/.test(n)),false);
    const bad=await invoke("tools/call",{
      name:"get_project_presence",arguments:{project_id:id}
    },"invalid","get_project_presence");
    assert.equal(bad.status,401);
    const foreign=await invoke("tools/call",{
      name:"get_project_presence",arguments:{project_id:id}
    },"test-user-b","get_project_presence");
    assert.equal(foreign.status,200);
    assert.match(JSON.stringify(foreign.data),/available/);
    assert.doesNotMatch(JSON.stringify(foreign.data),/boardPresent/);
    assert.equal(reads,0);
    const present=await invoke("tools/call",{
      name:"get_project_presence",arguments:{project_id:id}
    },"test-user-a","get_project_presence");
    assert.equal(present.status,200,JSON.stringify(present.data));
    assert.match(JSON.stringify(present.data),/"projectPresent":true/);
    assert.match(JSON.stringify(present.data),/"boardPresent":true/);
    assert.doesNotMatch(JSON.stringify(present.data),/USB-C Controller|\/home\/|localPath|run_drc/);
    assert.equal(reads,1);
    const implicit=await invoke("tools/call",{
      name:"get_project_presence",arguments:{}
    },"test-user-a","get_project_presence");
    assert.equal(implicit.status,200);
    assert.match(JSON.stringify(implicit.data),/"projectPresent":true/);
    assert.equal(reads,2,"single granted project should be selected implicitly");
    revokeDuringRead=true;
    const revoked=await invoke("tools/call",{
      name:"get_project_presence",arguments:{project_id:id}
    },"test-user-a","get_project_presence");
    assert.equal(revoked.status,200);
    assert.doesNotMatch(JSON.stringify(revoked.data),/boardPresent/);
    assert.match(JSON.stringify(revoked.data),/"available":false/);
    assert.equal(reads,3);
    grantActive=true;revokeDuringRead=false;accessAllowed=false;
    const cutoff=await invoke("tools/call",{
      name:"get_project_presence",arguments:{project_id:id}
    },"test-user-a","get_project_presence");
    assert.equal(cutoff.status,401);
    assert.equal(reads,3);
  }finally{
    grantActive=true;revokeDuringRead=false;accessAllowed=true;
    await new Promise<void>(resolve=>proxy.close(()=>resolve()));
  }
});

test("native DRC count tool is separate, scoped, revocable and OFF unless opted in",async()=>{
  let reads=0;
  let grantActive=true;
  let revokeDuringRead=false;
  const scoped:Inventory={
    ...inventory,
    async getProject(owner,clientId,projectId){
      if(!grantActive)return null;
      return inventory.getProject(owner,clientId,projectId);
    }
  };
  const relay={
    prepareOwnerSummary:testPrepared,
    async requestSummary(){return null;},
    prepareOwnerDrc(oauth:TrustedOAuthReadIdentity,deviceId:string,projectId:string){
      if(oauth.ownerSub!=="user-a"||oauth.clientId!=="test-client"||
        deviceId!==mockProject.deviceId||projectId!==id)return null;
      return {...testPrepared(oauth,deviceId,projectId),operation:"run_drc" as const};
    },
    async requestDrc(_oauth:TrustedOAuthReadIdentity,_deviceId:string,
      projectId:string,prepared:{requestId:string}){
      reads++;
      if(revokeDuringRead)grantActive=false;
      return {kind:"connector.local_drc_preview" as const,version:1 as const,
        requestId:prepared.requestId,projectId,operation:"run_drc" as const,
        counts:{violations:2,unconnectedItems:0}};
    }
  };
  const disabled=createHttpServer(config,scoped,verify,{
    summaryRelay:()=>relay,mcpProjectPresenceEnabled:true
  });
  const enabled=createHttpServer(config,scoped,verify,{
    summaryRelay:()=>relay,mcpProjectPresenceEnabled:true,
    mcpProjectNativeDrcEnabled:true
  });
  try{
    for(const [proxy,isEnabled] of [[disabled,false],[enabled,true]] as const){
      await new Promise<void>(resolve=>proxy.listen(0,"127.0.0.1",resolve));
      const origin="http://127.0.0.1:"+(proxy.address() as AddressInfo).port;
      const invoke=async(method:string,params:object,token="test-user-a",name?:string)=>{
        const result=await fetch(origin+"/mcp",{
          method:"POST",headers:headers(token,method,name),body:payload(method,params)
        });
        return {status:result.status,data:await result.json() as Record<string,any>};
      };
      const tools=await invoke("tools/list",{});
      const names=(tools.data.result?.tools??[]).map((t:{name:string})=>t.name);
      assert.equal(names.includes("get_project_drc_counts"),isEnabled);
      if(!isEnabled)continue;
      const unauthorized=await invoke("tools/call",{
        name:"get_project_drc_counts",arguments:{project_id:id}
      },"invalid","get_project_drc_counts");
      assert.equal(unauthorized.status,401);
      const foreign=await invoke("tools/call",{
        name:"get_project_drc_counts",arguments:{project_id:id}
      },"test-user-b","get_project_drc_counts");
      assert.equal(foreign.status,200);
      assert.doesNotMatch(JSON.stringify(foreign.data),/violations/);
      assert.equal(reads,0);
      const accepted=await invoke("tools/call",{
        name:"get_project_drc_counts",arguments:{project_id:id}
      },"test-user-a","get_project_drc_counts");
      assert.equal(accepted.status,200,JSON.stringify(accepted.data));
      assert.match(JSON.stringify(accepted.data),/"violations":2/);
      assert.match(JSON.stringify(accepted.data),/"unconnectedItems":0/);
      assert.doesNotMatch(JSON.stringify(accepted.data),/USB-C Controller|localPath|\.kicad_pcb/);
      assert.equal(reads,1);
      const implicit=await invoke("tools/call",{
        name:"get_project_drc_counts",arguments:{}
      },"test-user-a","get_project_drc_counts");
      assert.equal(implicit.status,200);
      assert.match(JSON.stringify(implicit.data),/"violations":2/);
      assert.equal(reads,2);
      revokeDuringRead=true;
      const revoked=await invoke("tools/call",{
        name:"get_project_drc_counts",arguments:{project_id:id}
      },"test-user-a","get_project_drc_counts");
      assert.equal(revoked.status,200);
      assert.match(JSON.stringify(revoked.data),/"available":false/);
      assert.doesNotMatch(JSON.stringify(revoked.data),/"violations"/);
      assert.equal(reads,3);
    }
  }finally{
    grantActive=true;
    revokeDuringRead=false;
    for(const proxy of [disabled,enabled]){
      if(proxy.listening)await new Promise<void>(resolve=>proxy.close(()=>resolve()));
    }
  }
});


test("Cloud presence selects only unambiguous granted projects",async()=>{
  const another={...mockProject,id:randomUUID(),alias:"Sensor Board"};
  let relayed=0;
  const scoped:Inventory={
    ...inventory,
    async listProjects(owner,clientId){
      return owner==="user-a"&&clientId==="test-client" ? [mockProject,another] : [];
    },
    async getProject(owner,clientId,projectId){
      return owner==="user-a"&&clientId==="test-client"
        ? [mockProject,another].find(project=>project.id===projectId)??null : null;
    }
  };
  const relay={
    prepareOwnerSummary:testPrepared,
    async requestSummary(_oauth:unknown,_device:string,projectId:string,
      prepared:PreparedOwnerSummary){
      relayed++;
      return {kind:"connector.local_read_preview" as const,version:1 as const,
        requestId:prepared.requestId,projectId,operation:"project_summary" as const,
        files:{projectPresent:true,boardPresent:true,schematicPresent:false}};
    }
  };
  const proxy=createHttpServer(config,scoped,verify,{
    summaryRelay:()=>relay,mcpProjectPresenceEnabled:true
  });
  await new Promise<void>(done=>proxy.listen(0,"127.0.0.1",done));
  const origin="http://127.0.0.1:"+(proxy.address() as AddressInfo).port;
  const invoke=async(token:string,args:object)=>{
    const response=await fetch(origin+"/mcp",{
      method:"POST",headers:headers(token,"tools/call","get_project_presence"),
      body:payload("tools/call",{name:"get_project_presence",arguments:args})
    });
    return {status:response.status,body:JSON.stringify(await response.json())};
  };
  try{
    const ambiguous=await invoke("test-user-a",{});
    assert.equal(ambiguous.status,200);
    assert.match(ambiguous.body,/"selectionRequired":true/);
    assert.doesNotMatch(ambiguous.body,/boardPresent/);
    const foreign=await invoke("test-user-b",{});
    assert.equal(foreign.status,200);
    assert.doesNotMatch(foreign.body,/selectionRequired":true/);
    assert.equal(relayed,0,"ambiguous and foreign calls must not reach the device");
    const selected=await invoke("test-user-a",{project_id:another.id});
    assert.equal(selected.status,200);
    assert.match(selected.body,/"boardPresent":true/);
    assert.equal(relayed,1);
  }finally{
    await new Promise<void>(done=>proxy.close(()=>done()));
  }
});


test("implicit project selection rechecks a grant after listing",async()=>{
  let projectLookups=0,relayed=0;
  const stale:Inventory={
    ...inventory,
    async listProjects(){return [mockProject];},
    async getProject(){projectLookups++;return null;}
  };
  const relay={
    prepareOwnerSummary:testPrepared,
    async requestSummary(){relayed++;return null;}
  };
  const proxy=createHttpServer(config,stale,verify,{
    summaryRelay:()=>relay,mcpProjectPresenceEnabled:true
  });
  await new Promise<void>(done=>proxy.listen(0,"127.0.0.1",done));
  const origin="http://127.0.0.1:"+(proxy.address() as AddressInfo).port;
  try{
    const response=await fetch(origin+"/mcp",{
      method:"POST",headers:headers("test-user-a","tools/call","get_project_presence"),
      body:payload("tools/call",{name:"get_project_presence",arguments:{}})
    });
    assert.equal(response.status,200);
    const output=JSON.stringify(await response.json());
    assert.match(output,/"available":false/);
    assert.doesNotMatch(output,/boardPresent/);
    assert.equal(projectLookups,1);
    assert.equal(relayed,0);
  }finally{
    await new Promise<void>(done=>proxy.close(()=>done()));
  }
});

test("manual project-engine status tool is explicit, scoped, path-free and revocable",async()=>{
  let reads=0,grantActive=true,revokeDuringRead=false;
  const scoped:Inventory={
    ...inventory,
    async getProject(owner,clientId,projectId){
      if(!grantActive)return null;
      return inventory.getProject(owner,clientId,projectId);
    }
  };
  const relay={
    prepareOwnerSummary:testPrepared,
    async requestSummary(){return null;},
    prepareOwnerInspection(oauth:TrustedOAuthReadIdentity,deviceId:string,projectId:string){
      if(oauth.ownerSub!=="user-a"||oauth.clientId!=="test-client"||
        deviceId!==mockProject.deviceId||projectId!==id)return null;
      return {...testPrepared(oauth,deviceId,projectId),
        operation:"project_worker_inspection" as const};
    },
    async requestInspection(_oauth:TrustedOAuthReadIdentity,_deviceId:string,
      projectId:string,prepared:{requestId:string}){
      reads++;
      if(revokeDuringRead)grantActive=false;
      return {kind:"connector.local_worker_inspection" as const,version:1 as const,
        requestId:prepared.requestId,projectId,operation:"project_worker_inspection" as const,
        status:{engineVersion:"4.6.1",cliAvailable:true,ipcAvailable:false,
          capabilities:{fileBackedDrc:true,fileBackedErc:true,
            livePcbRead:false,liveSchematicRead:false}}};
    }
  };
  const disabled=createHttpServer(config,scoped,verify,{
    summaryRelay:()=>relay,mcpProjectPresenceEnabled:true
  });
  const enabled=createHttpServer(config,scoped,verify,{
    summaryRelay:()=>relay,mcpProjectPresenceEnabled:true,
    mcpProjectInspectionEnabled:true
  });
  try{
    for(const [proxy,isEnabled] of [[disabled,false],[enabled,true]] as const){
      await new Promise<void>(done=>proxy.listen(0,"127.0.0.1",done));
      const origin="http://127.0.0.1:"+(proxy.address() as AddressInfo).port;
      const invoke=async(method:string,params:object,token="test-user-a",name?:string)=>{
        const result=await fetch(origin+"/mcp",{
          method:"POST",headers:headers(token,method,name),body:payload(method,params)
        });
        return {status:result.status,data:await result.json() as Record<string,any>};
      };
      const list=await invoke("tools/list",{});
      const names=(list.data.result?.tools??[]).map((t:{name:string})=>t.name);
      assert.equal(names.includes("get_project_engine_status"),isEnabled);
      if(!isEnabled)continue;
      const foreign=await invoke("tools/call",{
        name:"get_project_engine_status",arguments:{project_id:id}
      },"test-user-b","get_project_engine_status");
      assert.equal(foreign.status,200);
      assert.doesNotMatch(JSON.stringify(foreign.data),/engineVersion/);
      assert.equal(reads,0);
      const accepted=await invoke("tools/call",{
        name:"get_project_engine_status",arguments:{project_id:id}
      },"test-user-a","get_project_engine_status");
      assert.equal(accepted.status,200);
      assert.match(JSON.stringify(accepted.data),/"engineVersion":"4\.6\.1"/);
      assert.match(JSON.stringify(accepted.data),/"cliAvailable":true/);
      assert.match(JSON.stringify(accepted.data),/"fileBackedDrc":true/);
      assert.match(JSON.stringify(accepted.data),/"liveSchematicRead":false/);
      assert.doesNotMatch(JSON.stringify(accepted.data),/localPath|kicad_pcb|PRIVATE/);
      assert.equal(reads,1);
      const implicit=await invoke("tools/call",{
        name:"get_project_engine_status",arguments:{}
      },"test-user-a","get_project_engine_status");
      assert.equal(implicit.status,200);
      assert.match(JSON.stringify(implicit.data),/"ipcAvailable":false/);
      assert.equal(reads,2);
      revokeDuringRead=true;
      const revoked=await invoke("tools/call",{
        name:"get_project_engine_status",arguments:{project_id:id}
      },"test-user-a","get_project_engine_status");
      assert.equal(revoked.status,200);
      assert.match(JSON.stringify(revoked.data),/"available":false/);
      assert.doesNotMatch(JSON.stringify(revoked.data),/engineVersion/);
      assert.equal(reads,3);
    }
  }finally{
    revokeDuringRead=false;grantActive=true;
    await new Promise<void>(done=>disabled.close(()=>done()));
    await new Promise<void>(done=>enabled.close(()=>done()));
  }
});


test("board-count MCP tool stays absent unless opted in and rechecks owner grants",async()=>{
  let calls=0,active=true;
  const scoped:Inventory={
    ...inventory,
    async getProject(owner,client,projectId){
      if(!active)return null;
      return inventory.getProject(owner,client,projectId);
    }
  };
  const relay={
    prepareOwnerSummary:testPrepared,
    async requestSummary(){return null;},
    prepareOwnerBoardCounts:(_oauth:TrustedOAuthReadIdentity,_device:string,
      projectId:string)=>({...testPrepared(
        {ownerSub:"user-a",clientId:"test-client",accessTokenIssuedAtSeconds:0},
        mockProject.deviceId,projectId),operation:"project_board_counts" as const}),
    async requestBoardCounts(_oauth:TrustedOAuthReadIdentity,_device:string,
      projectId:string,intent:{requestId:string}){
      calls++;
      return {kind:"connector.local_board_counts" as const,version:1 as const,
        requestId:intent.requestId,projectId,operation:"project_board_counts" as const,
        source:"file-backed" as const,
        counts:{tracks:2,vias:3,footprints:4,zones:5,nets:6,shapes:7}};
    }
  };
  const enabled=createHttpServer(config,scoped,verify,{
    summaryRelay:()=>relay,mcpProjectBoardCountsEnabled:true
  });
  await new Promise<void>(resolve=>enabled.listen(0,"127.0.0.1",resolve));
  const origin="http://127.0.0.1:"+(enabled.address() as AddressInfo).port;
  const invoke=async(token:string,projectId=id)=>{
    const res=await fetch(origin+"/mcp",{
      method:"POST",headers:headers(token,"tools/call","get_project_board_counts"),
      body:payload("tools/call",{
        name:"get_project_board_counts",arguments:{project_id:projectId}
      })
    });
    return {status:res.status,text:JSON.stringify(await res.json())};
  };
  try{
    const other=await invoke("test-user-b");
    assert.equal(other.status,200);
    assert.match(other.text,/"available":false/);
    assert.equal(calls,0);
    const granted=await invoke("test-user-a");
    assert.equal(granted.status,200);
    assert.match(granted.text,/"available":true/);
    assert.match(granted.text,/"footprints":4/);
    assert.doesNotMatch(granted.text,/localPath|board\.kicad_pcb/);
    assert.equal(calls,1);
    active=false;
    const revoked=await invoke("test-user-a");
    assert.match(revoked.text,/"available":false/);
    assert.doesNotMatch(revoked.text,/"footprints"/);
    assert.equal(calls,1);
  }finally{
    await new Promise<void>(resolve=>enabled.close(()=>resolve()));
  }
});


test("schematic counts read obeys project grant and hides identifiers",async()=>{
  let calls=0,active=true;
  const scoped:Inventory={
    ...inventory,
    async getProject(owner,client,projectId){
      if(!active)return null;
      return inventory.getProject(owner,client,projectId);
    }
  };
  const relay={
    prepareOwnerSummary:testPrepared,
    async requestSummary(){return null;},
    prepareOwnerSchematicCounts:(_oauth:TrustedOAuthReadIdentity,_device:string,
      projectId:string)=>({...testPrepared(
        {ownerSub:"user-a",clientId:"test-client",accessTokenIssuedAtSeconds:0},
        mockProject.deviceId,projectId),operation:"project_schematic_counts" as const}),
    async requestSchematicCounts(_oauth:TrustedOAuthReadIdentity,_device:string,
      projectId:string,intent:{requestId:string}){
      calls++;
      return {kind:"connector.local_schematic_counts" as const,version:1 as const,
        requestId:intent.requestId,projectId,operation:"project_schematic_counts" as const,
        counts:{components:5,populated:4,dnp:1,inBom:4}};
    }
  };
  const enabled=createHttpServer(config,scoped,verify,{
    summaryRelay:()=>relay,mcpProjectSchematicCountsEnabled:true
  });
  await new Promise<void>(resolve=>enabled.listen(0,"127.0.0.1",resolve));
  const origin="http://127.0.0.1:"+(enabled.address() as AddressInfo).port;
  const invoke=async(token:string,projectId=id)=>{
    const res=await fetch(origin+"/mcp",{
      method:"POST",headers:headers(token,"tools/call","get_project_schematic_counts"),
      body:payload("tools/call",{
        name:"get_project_schematic_counts",arguments:{project_id:projectId}
      })
    });
    return {status:res.status,text:JSON.stringify(await res.json())};
  };
  try{
    const outsider=await invoke("test-user-b");
    assert.equal(outsider.status,200);
    assert.match(outsider.text,/"available":false/);
    assert.equal(calls,0);
    const granted=await invoke("test-user-a");
    assert.equal(granted.status,200);
    assert.match(granted.text,/"available":true/);
    assert.match(granted.text,/"components":5/);
    assert.doesNotMatch(granted.text,/localPath|reference|sheet_file/);
    assert.equal(calls,1);
    active=false;
    const revoked=await invoke("test-user-a");
    assert.match(revoked.text,/"available":false/);
    assert.doesNotMatch(revoked.text,/"components"/);
    assert.equal(calls,1);
  }finally{
    await new Promise<void>(resolve=>enabled.close(()=>resolve()));
  }
});
