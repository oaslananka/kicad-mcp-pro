import assert from "node:assert/strict";
import {randomUUID} from "node:crypto";
import type {AddressInfo} from "node:net";
import {test} from "node:test";
import {createHttpServer} from "../src/http.js";
import type {Config} from "../src/config.js";
import type {Inventory} from "../src/store.js";
import type {BrowserIdentity} from "../src/browser.js";
import type {DeviceManagementPort} from "../src/devices.js";
import type {LocalFolderPort} from "../src/connector-ws.js";

test("production HTTP serves device actions and navigates remote nested folders",async()=>{
  const origin="http://127.0.0.1",id=randomUUID(),owner="browser-owner";
  const config:Config={
    host:"127.0.0.1",port:0,publicOrigin:origin,
    issuer:"https://issuer.test",jwksUrl:"https://issuer.test/jwks",
    audience:origin+"/mcp",databaseUrl:"unused",
    allowedOrigins:[],managementClientId:"manager"
  };
  const inventory={
    isAccessTokenAllowed:async()=>false,
    listDevices:async()=>[],listProjects:async()=>[],getProject:async()=>null
  } as Inventory;
  const identity={
    handler:async()=>new Response(null,{status:404}),
    $context:Promise.resolve({secret:"long-test-owner-session-key-at-least-32-characters"}),
    api:{getSession:async()=>({session:{id:"owner-session"},
      user:{id:owner}})}
  } as unknown as BrowserIdentity;
  const devices:DeviceManagementPort={
    list:async(u)=>u===owner?[{
      id,alias:"Remote KiCad",enabled:true,revoked:false,
      fingerprint:"a".repeat(64),createdAt:new Date()
    }]:[],
    listProjects:async()=>[],
    revokeDevice:async()=>false
  };
  const folderCalls:string[]=[];
  const localFolders:LocalFolderPort={
    supportsBrowse:(u,d)=>u===owner&&d===id,
    getProjectPath:async()=>null,chooseFolder:async()=>null,
    bindFolder:async()=>false,
    listFolder:async(u,d,folderId)=>{
      folderCalls.push(folderId);
      if(u!==owner||d!==id)return null;
      if(folderId==="root")return{
        folderId:"root",name:"This computer",parentId:null,
        project:false,more:false,
        folders:[{id:"child-token",name:"Motor Board",project:true}]
      };
      if(folderId==="child-token")return{
        folderId:"child-token",name:"Motor Board",parentId:"root",
        project:true,more:false,folders:[]
      };
      return null;
    }
  };
  const relay={localFolders,isDeviceConnected:(u:string,d:string)=>
    u===owner&&d===id,prepareOwnerSummary:()=>null,requestSummary:async()=>null};
  const server=createHttpServer(config,inventory,async()=>{throw Error("invalid");},
    {identity,devices,summaryRelay:()=>relay as never});
  await new Promise<void>(resolve=>server.listen(0,"127.0.0.1",resolve));
  const url="http://127.0.0.1:"+(server.address() as AddressInfo).port;
  try{
    const page=await fetch(url+"/devices");
    assert.equal(page.status,200);
    const html=await page.text();
    assert.match(html,/src="\/assets\/device-projects\.js"/);
    const asset=await fetch(url+"/assets/device-projects.js");
    assert.equal(asset.status,200);
    assert.match(asset.headers.get("content-type")??"",/text\/javascript/);
    assert.match(await asset.text(),/showModal/);
    const copy=await fetch(url+"/assets/copy-value.js");
    assert.equal(copy.status,200);
    assert.match(copy.headers.get("content-type")??"",/text\/javascript/);
    assert.equal(copy.headers.get("x-content-type-options"),"nosniff");
    assert.match(await copy.text(),/navigator\.clipboard\.writeText/);
    const browseCsrf=/<form[^>]*action="\/devices\/projects\/browse"[^>]*[\s\S]*?name="csrf" value="([^"]+)"/
      .exec(html)?.[1];
    assert.ok(browseCsrf);
    const postHeaders=(cookie:string,from=origin)=>({
      Origin:from,Cookie:cookie,
      "Content-Type":"application/x-www-form-urlencoded"
    });
    const cookie=(page.headers.get("set-cookie")??"").split(";")[0];
    const root=await fetch(url+"/devices/projects/browse",{
      method:"POST",headers:postHeaders(cookie),
      body:new URLSearchParams({device_id:id,csrf:browseCsrf})
    });
    assert.equal(root.status,200);
    const rootHtml=await root.text();
    assert.match(rootHtml,/Motor Board/);
    const folderForm=/<form action="\/devices\/projects\/folders" method="post">([\s\S]*?)<\/form>/
      .exec(rootHtml)?.[1]??"";
    const openCsrf=/name="csrf" value="([^"]+)"/.exec(folderForm)?.[1];
    assert.ok(openCsrf);
    const folderCookie=(root.headers.get("set-cookie")??"").split(";")[0];
    const forged=await fetch(url+"/devices/projects/folders",{
      method:"POST",headers:postHeaders(folderCookie,"https://attacker.example"),
      body:new URLSearchParams({device_id:id,folder_id:"child-token",csrf:openCsrf}),
      redirect:"manual"
    });
    assert.equal(forged.status,403);
    assert.deepEqual(folderCalls,["root"]);
    const child=await fetch(url+"/devices/projects/folders",{
      method:"POST",headers:postHeaders(folderCookie),
      body:new URLSearchParams({device_id:id,folder_id:"child-token",csrf:openCsrf}),
      redirect:"manual"
    });
    assert.equal(child.status,200);
    assert.match(await child.text(),/Add this project/);
    assert.deepEqual(folderCalls,["root","child-token"]);
  }finally{
    await new Promise<void>(resolve=>server.close(()=>resolve()));
  }
});
