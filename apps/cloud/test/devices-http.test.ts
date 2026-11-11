import assert from "node:assert/strict";
import {createServer,type Server} from "node:http";
import type {AddressInfo} from "node:net";
import {test} from "node:test";
import {randomUUID} from "node:crypto";
import {createHttpServer} from "../src/http.js";
import type {Config} from "../src/config.js";
import type {Inventory} from "../src/store.js";
import type {BrowserIdentity} from "../src/browser.js";
import type {DeviceManagementPort} from "../src/devices.js";

const id=randomUUID();
const config:Config={
  host:"127.0.0.1",port:0,publicOrigin:"http://127.0.0.1",
  issuer:"https://issuer.example",jwksUrl:"https://issuer.example/jwks",
  audience:"http://127.0.0.1/mcp",databaseUrl:"not-used",
  allowedOrigins:[],managementClientId:"manager"
};
const inventory={
  isAccessTokenAllowed:async()=>false,
  listDevices:async()=>[],listProjects:async()=>[],getProject:async()=>null
} as Inventory;
const identity={
  handler:async()=>new Response(null,{status:404}),
  $context:Promise.resolve({secret:"test-http-devices-secret-minimum-thirty-two-bytes"}),
  api:{getSession:async()=>({session:{id:"owner-session"},user:{id:"owner-1"}})}
} as unknown as BrowserIdentity;
const calls:string[]=[];
let deviceEnabled=false;
const registeredProjects:Array<{id:string;deviceId:string;alias:string;enabled:boolean}>=[];
const devices:DeviceManagementPort={
  list:async(owner)=>owner==="owner-1"?[{
    id,alias:"My KiCad",enabled:deviceEnabled,revoked:false,
    fingerprint:"a".repeat(64),createdAt:new Date()
  }]:[],
  enableDevice:async(owner,device)=>{
    if(owner!=="owner-1"||device!==id)return false;
    deviceEnabled=true;return true;
  },
  createProject:async(owner,device,alias)=>{
    if(owner!=="owner-1"||device!==id||!deviceEnabled)return null;
    registeredProjects.push({id:"77777777-7777-4777-8777-777777777777",deviceId:device,
      alias,enabled:true});
    return registeredProjects.at(-1)?.id??null;
  },
  listProjects:async(owner)=>owner==="owner-1"?registeredProjects:[],
  revokeDevice:async(owner,device)=>{
    calls.push(owner+":"+device);
    return owner==="owner-1"&&device===id;
  }
};
async function startServer(server:Server):Promise<{origin:string;close:()=>Promise<void>}>{
  await new Promise<void>(resolve=>server.listen(0,"127.0.0.1",resolve));
  const origin="http://127.0.0.1:"+(server.address() as AddressInfo).port;
  return {origin,close:()=>new Promise(resolve=>server.close(()=>resolve()))};
}
test("HTTP device routes are absent without builtin identity",async()=>{
  const s=await startServer(createHttpServer(config, inventory, async()=>{
    throw Error("invalid");
  }));
  try{
    const res=await fetch(s.origin+"/devices");
    assert.equal(res.status,404);
    const action=await fetch(s.origin+"/devices/revoke",{
      method:"POST",body:"device_id="+id,
      headers:{Origin:config.publicOrigin}
    });
    assert.equal(action.status,404);
    const removal=await fetch(s.origin+"/devices/delete",{
      method:"POST",body:"device_id="+id,
      headers:{Origin:config.publicOrigin}
    });
    assert.equal(removal.status,404,
      "permanent removal must not be available without a browser identity");
  }finally{await s.close();}
});
test("HTTP device revocation uses verified browser session plus CSRF",async()=>{
  const s=await startServer(createHttpServer(config, inventory, async()=>{
    throw Error("unused");
  }, {identity:identity, devices:devices}));
  try{
    const view=await fetch(s.origin+"/devices");
    assert.equal(view.status,200);
    const html=await view.text();
    assert.match(html,/My KiCad/);
    const token=/name="csrf" value="([^"]+)"/.exec(html)?.[1]??"";
    assert.ok(token);
    const cookie=(view.headers.get("set-cookie")??"").split(";")[0];
    const form=new URLSearchParams({device_id:id,csrf:token});
    const denied=await fetch(s.origin+"/devices/revoke",{
      method:"POST",headers:{
        "Content-Type":"application/x-www-form-urlencoded",
        Cookie:cookie,Origin:"https://attacker.example"
      },body:form,redirect:"manual"
    });
    assert.equal(denied.status,403);
    const success=await fetch(s.origin+"/devices/revoke",{
      method:"POST",headers:{
        "Content-Type":"application/x-www-form-urlencoded",
        Cookie:cookie,Origin:config.publicOrigin
      },body:form,redirect:"manual"
    });
    assert.equal(success.status,303);
    assert.equal(success.headers.get("location"),"/devices?revoked=1");
    assert.deepEqual(calls,["owner-1:"+id]);
  }finally{await s.close();}
});


test("permanent removal from the actual HTTP page routes only a valid revoked-device POST",async()=>{
  const removed:string[]=[];
  let gone=false;
  const revokedDevices:DeviceManagementPort={
    ...devices,
    async list(owner){
      if(owner!=="owner-1"||gone)return [];
      return [{id,alias:"Revoked KiCad",enabled:false,revoked:true,
        fingerprint:"b".repeat(64),createdAt:new Date()}];
    },
    async deleteRevokedDevice(owner,device){
      if(owner!=="owner-1"||device!==id||gone)return false;
      removed.push(owner+":"+device);gone=true;return true;
    }
  };
  const server=await startServer(createHttpServer(config,inventory,async()=>{
    throw Error("unused");
  },{identity,devices:revokedDevices}));
  try{
    const open=await fetch(server.origin+"/devices/delete",{redirect:"manual"});
    assert.equal(open.status,303,
      "GET is navigation only: never show raw not_found or perform a deletion");
    assert.equal(open.headers.get("location"),"/devices");
    assert.equal(removed.length,0);

    const page=await fetch(server.origin+"/devices");
    const html=await page.text();
    assert.match(html,/Revoked KiCad/);
    assert.match(html,/<form action="\/devices\/delete" method="post">/);
    const token=/<form action="\/devices\/delete" method="post">[\s\S]*?name="csrf" value="([^"]+)"/
      .exec(html)?.[1]??"";
    const cookie=(page.headers.get("set-cookie")??"").split(";")[0];
    assert.ok(token&&cookie);
    const form=new URLSearchParams({device_id:id,csrf:token});
    const headers={"Content-Type":"application/x-www-form-urlencoded",
      Cookie:cookie,Origin:config.publicOrigin};
    const malicious=await fetch(server.origin+"/devices/delete",{
      method:"POST",headers:{...headers,Origin:"https://attacker.invalid"},
      body:form,redirect:"manual"
    });
    assert.equal(malicious.status,403);
    assert.deepEqual(removed,[]);
    const invalid=await fetch(server.origin+"/devices/delete",{
      method:"POST",headers:{...headers,Cookie:""},body:form,redirect:"manual"
    });
    assert.equal(invalid.status,403);
    assert.deepEqual(removed,[]);

    const valid=await fetch(server.origin+"/devices/delete",{
      method:"POST",headers,body:form,redirect:"manual"
    });
    assert.equal(valid.status,303,"successful removal must return to the devices page");
    assert.equal(valid.headers.get("location"),"/devices?deleted=1");
    assert.deepEqual(removed,["owner-1:"+id]);
    const done=await fetch(server.origin+"/devices?deleted=1");
    assert.equal(done.status,200);
    const result=await done.text();
    assert.match(result,/Revoked device and its registered projects were permanently removed/);
    assert.doesNotMatch(result,/Revoked KiCad/);
  }finally{await server.close();}
});

test("owner device activation and read-only project creation are disabled by default, CSRF scoped",
  async()=>{
  const disabled=await startServer(createHttpServer(config, inventory, async()=>{
    throw Error("unused");
  }, {identity:identity, devices:devices}));
  try{
    const denied=await fetch(disabled.origin+"/devices/enable",{
      method:"POST",headers:{Origin:config.publicOrigin},body:""});
    assert.equal(denied.status,405);
  }finally{await disabled.close();}
  const enabled=await startServer(createHttpServer(config, inventory, async()=>{
    throw Error("unused");
  }, {identity:identity, devices:devices, pairingDevice:{} as never}));
  try{
    const page=await fetch(enabled.origin+"/devices");
    assert.equal(page.headers.get("referrer-policy"),"same-origin",
      "first-party device forms must retain the browser Origin for strict POST validation");
    const html=await page.text();
    assert.match(html,/Enable my device/);
    const csrf=/<form action="\/devices\/enable"[\s\S]*?name="csrf" value="([^"]+)"/.exec(html)?.[1]??"";
    const wrong=/<form action="\/devices\/revoke"[\s\S]*?name="csrf" value="([^"]+)"/.exec(html)?.[1]??"";
    const cookie=(page.headers.get("set-cookie")??"").split(";")[0];
    assert.ok(csrf&&wrong);
    const headers={"Content-Type":"application/x-www-form-urlencoded",
      Origin:config.publicOrigin,Cookie:cookie};
    const send=(body:URLSearchParams)=>fetch(enabled.origin+"/devices/enable",{
      method:"POST",headers,body,redirect:"manual"});
    assert.equal((await send(new URLSearchParams({device_id:id,csrf:wrong}))).status,403);
    assert.equal(deviceEnabled,false);
    assert.equal((await send(new URLSearchParams({device_id:id,csrf}))).status,303);
    assert.equal(deviceEnabled,true);
    const updated=await fetch(enabled.origin+"/devices");
    const projectHtml=await updated.text();
    assert.match(projectHtml,/Register project name/);
    const projectCsrf=/<form action="\/devices\/projects\/create"[\s\S]*?name="csrf" value="([^"]+)"/.exec(projectHtml)?.[1]??"";
    const projectCookie=(updated.headers.get("set-cookie")??"").split(";")[0];
    assert.ok(projectCsrf);
    const created=await fetch(enabled.origin+"/devices/projects/create",{
      method:"POST",headers:{"Content-Type":"application/x-www-form-urlencoded",
        Origin:config.publicOrigin,Cookie:projectCookie},redirect:"manual",
      body:new URLSearchParams({device_id:id,alias:"Approved Demo",csrf:projectCsrf})
    });
    assert.equal(created.status,303);
    assert.equal(registeredProjects.at(-1)?.alias,"Approved Demo");
    const refreshed=await (await fetch(enabled.origin+"/devices")).text();
    assert.match(refreshed,/Approved Demo/);
    assert.match(refreshed,/On device: My KiCad/);
    assert.doesNotMatch(refreshed,/Registered project IDs/);
    assert.doesNotMatch(refreshed,/<code>77777777-7777-4777-8777-777777777777<\/code>/);
    assert.doesNotMatch(refreshed,/local file path/i);
  }finally{await enabled.close();}
});

test("owner approves only an OAuth-consented AI client's read-only project grant",async()=>{
  deviceEnabled=true;
  registeredProjects.splice(0,registeredProjects.length,{
    id:"77777777-7777-4777-8777-777777777777",deviceId:id,alias:"Fixture",enabled:true
  });
  const actor={...identity,api:{...identity.api,
    getOAuthConsents:async()=>[
      {id:"approved",userId:"owner-1",clientId:"ai-fixture",scopes:["projects:read"]},
      {id:"foreign",userId:"owner-2",clientId:"other-owner",scopes:["projects:read"]},
      {id:"other-scope",userId:"owner-1",clientId:"not-allowed",scopes:["openid"]}
    ]}} as unknown as BrowserIdentity;
  const requests:Array<{owner:string;project:string;client:string;enabled:boolean}>=[];
  const grants={
    listBrowserGrants:async(owner:string)=>owner==="owner-1"?[{
      projectId:registeredProjects[0].id,clientId:"ai-fixture",maxMode:"readonly" as const
    }]:[],
    setGrant:async()=>false,
    revokeClient:async()=>0,
    setBrowserGrant:async(owner:string,project:string,client:string,enabled:boolean)=>{
      requests.push({owner,project,client,enabled});
      return owner==="owner-1"&&client==="ai-fixture";
    }
  };
  const web=await startServer(createHttpServer(config, inventory, async()=>{
    throw Error("unused");
  }, {grants:grants, identity:actor, devices:devices, pairingDevice:{} as never}));
  try{
    const page=await fetch(web.origin+"/devices");
    const html=await page.text();
    // The already-granted client is listed but not offered for a redundant grant.
    assert.doesNotMatch(html,/AI application/);
    assert.match(html,/ai-fixture/);
    assert.match(html,/Applications with access/);
    assert.match(html,/Remove this app access/);
    assert.doesNotMatch(html,/other-owner|not-allowed/);
    const token=/action="\/devices\/projects\/grant"[\s\S]*?name="csrf" value="([^"]+)"/.exec(html)?.[1]??"";
    assert.ok(token);
    const cookie=(page.headers.get("set-cookie")??"").split(";")[0];
    const headers={Origin:config.publicOrigin,
      "Content-Type":"application/x-www-form-urlencoded",Cookie:cookie};
    const data=new URLSearchParams({project_id:registeredProjects[0].id,
      client_id:"ai-fixture",enabled:"true",csrf:token});
    const bad=await fetch(web.origin+"/devices/projects/grant",{
      method:"POST",headers:{...headers,Origin:"https://bad.example"},
      body:data,redirect:"manual"
    });
    assert.equal(bad.status,403);
    assert.equal(requests.length,0);
    const approved=await fetch(web.origin+"/devices/projects/grant",{
      method:"POST",headers,body:data,redirect:"manual"
    });
    assert.equal(approved.status,303);
    assert.equal(approved.headers.get("location"),"/devices?access=granted");
    assert.deepEqual(requests,[{owner:"owner-1",project:registeredProjects[0].id,
      client:"ai-fixture",enabled:true}]);
    data.set("enabled","false");
    const removed=await fetch(web.origin+"/devices/projects/grant",{
      method:"POST",headers,body:data,redirect:"manual"
    });
    assert.equal(removed.status,303);
    assert.equal(removed.headers.get("location"),"/devices?access=removed");
    assert.equal(requests[1].enabled,false);
  }finally{await web.close();}
});
