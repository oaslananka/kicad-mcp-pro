import assert from "node:assert/strict";
import {randomUUID} from "node:crypto";
import type {AddressInfo} from "node:net";
import {test} from "node:test";
import {renderProjectsPage} from "../src/projects-ui.js";
import {createHttpServer} from "../src/http.js";
import type {BrowserIdentity} from "../src/browser.js";
import type {DeviceManagementPort} from "../src/devices.js";
import type {Config} from "../src/config.js";
import type {Inventory} from "../src/store.js";
import {cliReturnCookie} from "../src/owner-cli-return.js";
import {browserResponse} from "../src/browser.js";

const deviceId=randomUUID(),projectId=randomUUID();
const device={id:deviceId,alias:"Studio PC",enabled:true,revoked:false,
  fingerprint:"fixture",createdAt:new Date(),csrf:"fixture",
  connectionState:"connected" as const};
const project={id:projectId,deviceId,alias:"Motor controller",enabled:true,
  managedEnabled:true};
const client="https://chatgpt.com/oauth/client.json";

test("project workspace explains each missing prerequisite without claiming execution readiness",()=>{
  for(const [devices,projects,clients,grants,state] of [
    [[{...device,enabled:false}],[project],[client],[],"device-paused"],
    [[{...device,connectionState:"disconnected" as const}],[project],[client],[],"device-offline"],
    [[{...device,connectionState:undefined}],[project],[client],[],"status-unknown"],
    [[device],[project],[],[],"connect-ai"],
    [[device],[project],[client],[],"grant-access"],
    [[device],[{...project,managedEnabled:false}],[client],
      [{projectId,clientId:client,maxMode:"readonly" as const}],"reads-paused"],
    [[device],[project],[client],
      [{projectId,clientId:client,maxMode:"readonly" as const}],"read-access-enabled"]
  ] as const){
    const html=renderProjectsPage(devices,projects,clients,grants);
    assert.ok(html.includes('data-project-state="'+state+'"'),state);
    assert.doesNotMatch(html,/Ready to edit|KiCad is running|All tools available/);
  }
  const revoked=renderProjectsPage([{...device,revoked:true}],[project],[client],[]);
  assert.match(revoked,/Device access revoked/);
  const stale=renderProjectsPage([device],[project],["another-client"],
    [{projectId,clientId:client,maxMode:"write"}]);
  assert.match(stale,/data-project-state="grant-access"/);
  assert.doesNotMatch(stale,/Read &amp; edit permission saved/);
});

test("project workspace keeps controls reachable, escapes names and separates saved write permission from availability",()=>{
  const html=renderProjectsPage([device],[{...project,alias:"<svg onload=bad>"}],
    [client],[{projectId,clientId:client,maxMode:"write"}]);
  assert.match(html,/href="\/projects" aria-current="page"/);
  assert.match(html,/&lt;svg onload=bad&gt;/);
  assert.ok(html.includes('href="/devices#project-'+projectId+'"'));
  assert.match(html,/Read &amp; edit permission saved/);
  assert.match(html,/Saving edit permission does not enable Cloud editing by itself/);
  const empty=renderProjectsPage([],[],[],[]);
  assert.match(empty,/Connect your first computer/);
  assert.match(empty,/href="\/devices#connect-computer"/);
  assert.match(empty,/<a class="button primary" href="\/devices#connect-computer">[\s\S]*?Connect computer<\/a>/);
  assert.match(renderProjectsPage([device],[]),/<a class="button primary" href="\/devices#registered-projects">[\s\S]*?Add project<\/a>/);
  const unavailable=renderProjectsPage([],[],[],[],false);
  assert.match(unavailable,/Project access is unavailable/);
  assert.doesNotMatch(unavailable,/Add project<|Connect computer</);
});

test("production projects route renders only the signed-in owner's inventory and denies unsigned navigation",async()=>{
  const origin="http://127.0.0.1",owner="project-owner";
  const config:Config={host:"127.0.0.1",port:0,publicOrigin:origin,
    issuer:"https://issuer.test",jwksUrl:"https://issuer.test/jwks",
    audience:origin+"/mcp",databaseUrl:"unused",allowedOrigins:[],managementClientId:"manager"};
  const identity={handler:async()=>new Response(null,{status:404}),
    $context:Promise.resolve({secret:"project-workspace-isolated-session-secret"}),
    api:{getSession:async({headers}:{headers:Headers})=>headers.get("cookie")?.includes("fixture-owner=1")?
      {session:{id:"fixture-session"},user:{id:owner,email:"owner@example.test"}}:null}
  } as unknown as BrowserIdentity;
  const devices:DeviceManagementPort={
    list:async user=>{assert.equal(user,owner);return [device];},
    listProjects:async user=>{assert.equal(user,owner);return [project];},
    revokeDevice:async()=>false
  };
  const inventory={isAccessTokenAllowed:async()=>false,listDevices:async()=>[],
    listProjects:async()=>[],getProject:async()=>null} as Inventory;
  const server=createHttpServer(config,inventory,async()=>{throw Error("unused");},
    {identity,devices,pairingDevice:{} as never});
  await new Promise<void>(resolve=>server.listen(0,"127.0.0.1",resolve));
  const base="http://127.0.0.1:"+(server.address() as AddressInfo).port;
  try{
    const denied=await fetch(base+"/projects",{redirect:"manual"});
    assert.equal(denied.status,303);
    assert.equal(denied.headers.get("location"),"/sign-in");
    const response=await fetch(base+"/projects",{headers:{Cookie:"fixture-owner=1"}});
    assert.equal(response.status,200);
    assert.match(response.headers.get("cache-control")??"",/\bno-store\b/);
    assert.equal(response.headers.get("set-cookie"),null,"read-only navigation must not invalidate open device forms");
    const html=await response.text();
    assert.match(html,/<title>Projects/);
    assert.match(html,/Motor controller/);
    assert.match(html,/Studio PC/);
    assert.match(html,/owner@example.test/);
    assert.match(html,/data-project-state="status-unknown"/);
    assert.match(html,/pairing-login-continuation\.js/);
    const requestId="r".repeat(43);
    const cli=await fetch(base+"/projects",{redirect:"manual",headers:{
      Cookie:"fixture-owner=1; "+cliReturnCookie(origin,requestId,600).split(";")[0]}});
    assert.equal(cli.status,303);
    assert.equal(cli.headers.get("location"),"/api/owner/cli/approve?request_id="+requestId);
    assert.match(cli.headers.get("set-cookie")??"",/Max-Age=0/);
  }finally{
    await new Promise<void>((resolve,reject)=>server.close(error=>error?reject(error):resolve()));
  }
});

test("social sign-in lands on projects while provider linking retains account security",async()=>{
  const origin="https://cloud.example.test";
  let callback="";
  const identity={handler:async(request:Request)=>{
    callback=(await request.json() as {callbackURL:string}).callbackURL;
    return Response.json({url:"https://github.com/login/oauth/authorize"});
  }} as BrowserIdentity;
  const response=await browserResponse(new Request(origin+"/auth/start/github",{
    method:"POST",headers:{Origin:origin,"Content-Type":"application/x-www-form-urlencoded"},
    body:"oauth_query="}),identity,origin);
  assert.equal(response?.status,303);
  assert.equal(callback,origin+"/projects");
});
