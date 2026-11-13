import assert from "node:assert/strict";
import {randomUUID} from "node:crypto";
import {test} from "node:test";
import type {BrowserIdentity} from "../src/browser.js";
import type {DeviceManagementPort} from "../src/devices.js";
import {devicesResponse} from "../src/devices.js";
import type {LocalFolderPort,NativeFolderSelection} from "../src/connector-ws.js";
import {renderLocalFolderPage} from "../src/local-folder-page.js";
import {validProjectAlias} from "../src/device-management.js";

const origin="http://127.0.0.1:8787";
const deviceId=randomUUID();
const projectId=randomUUID();
const folderToken="an-opaque-native-token";
const owner="local-dev-owner";
const folderName="\u00C7izim 2026";

function fixture(local=true,selection:NativeFolderSelection={
  status:"selected",folderId:folderToken,name:folderName,
  projects:[{id:folderToken,name:"Design"}]
}){
  let name="";
  let bindings=0;
  let removed=0;
  let chooserCalls=0;
  const identity={
    localDevSandbox:local,
    api:{getSession:async()=>({session:{id:"sandbox-session"},user:{id:owner}})},
    $context:Promise.resolve({secret:"a-secret-of-at-least-32-characters-for-tests"}),
    handler:async()=>new Response(null,{status:404})
  } as unknown as BrowserIdentity;
  const devices:DeviceManagementPort={
    list:async(u)=>u===owner?[{
      id:deviceId,alias:"Device & Lab",enabled:true,revoked:false,
      fingerprint:"d".repeat(64),createdAt:new Date()
    }]:[],
    createProject:async(u,d,alias)=>{
      if(u!==owner||d!==deviceId)return null;
      name=alias;return projectId;
    },
    renameProject:async(u,id,alias)=>{
      if(u!==owner||id!==projectId)return false;
      name=alias;return true;
    },
    deleteProject:async(u,id)=>{
      if(u===owner&&id===projectId){removed++;return true;}
      return false;
    },
    listProjects:async()=>name?[{id:projectId,deviceId,alias:name,enabled:true}]:[],
    revokeDevice:async()=>false
  };
  const listing={folderId:folderToken,name:folderName,parentId:null,project:true,
    more:false,folders:[]};
  const folders:LocalFolderPort={
    getProjectPath:async()=>null,
    chooseFolder:async(u,d)=>{
      chooserCalls++;
      return u===owner&&d===deviceId?selection:null;
    },
    listFolder:async(u,d,token)=>{
      if(u!==owner||d!==deviceId)return null;
      if(token===folderToken)return listing;
      if(!local&&token==="root")return {
        folderId:"root",name:"This computer",parentId:null,project:false,
        more:false,folders:[{id:folderToken,name:folderName,project:true}]
      };
      return null;
    },
    bindFolder:async(u,d,token,id)=>{
      bindings++;
      return u===owner&&d===deviceId&&token===folderToken&&id===projectId;
    }
  };
  const route=(url:string,request?:Request)=>
    devicesResponse(request??new Request(origin+url),identity,origin,devices,
      true,undefined,()=>true,undefined,folders);
  return {route,listing,identity,devices,folders,getName:()=>name,
    bindings:()=>bindings,removed:()=>removed,chooserCalls:()=>chooserCalls};
}

function ownerPost(path:string,values:Record<string,string>,cookie:string,
  requestOrigin=origin):Request{
  return new Request(origin+path,{
    method:"POST",headers:{
      Origin:requestOrigin,"Content-Type":"application/x-www-form-urlencoded",
      Cookie:cookie
    },body:new URLSearchParams(values)
  });
}

async function beginSelection(f:ReturnType<typeof fixture>){
  const listing=await f.route("/devices");
  assert.equal(listing?.status,200);
  const html=await listing!.text();
  const csrf=/<form[^>]*action="\/devices\/projects\/browse"[^>]*[\s\S]*?name="csrf" value="([^"]+)"/.exec(html)?.[1];
  assert.ok(csrf);
  const cookie=listing!.headers.get("set-cookie")?.split(";")[0]??"";
  return f.route("/devices/projects/browse",ownerPost("/devices/projects/browse",
    {device_id:deviceId,csrf},cookie));
}

test("selected project confirmation is minimal and escapes the device folder label",()=>{
  const page=renderLocalFolderPage(deviceId,{
    status:"selected",name:"<em>evil</em>",folderId:folderToken,
    projects:[{id:folderToken,name:"Design"}]
  },[{id:folderToken,name:"Design",csrf:"csrf"}]);
  assert.match(page,/Folder selected on your computer/);
  assert.match(page,/name="alias"/);
  assert.match(page,/Add this project/);
  assert.match(page,/&lt;em&gt;evil&lt;\/em&gt;/);
  assert.ok(!page.includes("<em>evil</em>"));
  assert.doesNotMatch(page,/folder-browser-list|Choose a location|C:\\Users\\/);
});

test("signed local device picker supplies a default name, then owner confirms registration",async()=>{
  const f=fixture();
  const view=await beginSelection(f);
  assert.equal(view?.status,200);
  assert.equal(f.chooserCalls(),1);
  const text=await view!.text();
  assert.match(text,/Folder selected on your computer/);
  assert.match(text,new RegExp('value="'+folderName+'"'));
  assert.doesNotMatch(text,/folder-browser-list|C:\\Users\\/);
  const csrf=/name="csrf" value="([^"]+)"/.exec(text)?.[1];
  assert.ok(csrf);
  const cookie=view!.headers.get("set-cookie")?.split(";")[0]??"";
  const selected=await f.route("/devices/projects/select",ownerPost(
    "/devices/projects/select",{device_id:deviceId,folder_id:folderToken,
      alias:folderName,csrf},cookie
  ));
  assert.equal(selected?.status,303);
  assert.equal(f.getName(),folderName);
  assert.equal(f.bindings(),1);
  assert.equal(f.removed(),0);
});

test("only same-origin CSRF-proven POST may open the native picker",async()=>{
  const f=fixture();
  assert.equal((await f.route("/devices/projects/browse?device_id="+deviceId))?.status,303);
  assert.equal(f.chooserCalls(),0);
  const post=ownerPost("/devices/projects/browse",{
    device_id:deviceId,csrf:"bad"
  },"kicad-devices=bad");
  assert.equal((await f.route("/devices/projects/browse",post))?.status,403);
  assert.equal(f.chooserCalls(),0);
  const page=await f.route("/devices");
  const csrf=/<form[^>]*action="\/devices\/projects\/browse"[^>]*[\s\S]*?name="csrf" value="([^"]+)"/.exec(await page!.text())?.[1];
  assert.ok(csrf);
  const cookie=page!.headers.get("set-cookie")?.split(";")[0]??"";
  const forged=ownerPost("/devices/projects/browse",{device_id:deviceId,csrf},
    cookie,"https://attacker.invalid");
  assert.equal((await f.route("/devices/projects/browse",forged))?.status,403);
  assert.equal(f.chooserCalls(),0);
  const live=fixture(false);
  const badProduction=ownerPost("/devices/projects/browse",{
    device_id:deviceId,csrf:"bad"
  },"kicad-devices=bad");
  assert.equal((await live.route("/devices/projects/browse",badProduction))?.status,403);
  assert.equal(live.chooserCalls(),0);
});

test("cancel and invalid folder selection create no project",async()=>{
  for(const status of ["cancelled","invalid"] as const){
    const f=fixture(true,{status});
    const result=await beginSelection(f);
    assert.equal(result?.status,303);
    assert.equal(result?.headers.get("location"),"/devices?picker="+status);
    assert.equal(f.getName(),"");
    assert.equal(f.bindings(),0);
  }
});

test("rename changes only the owner's project display name",async()=>{
  const f=fixture();
  await f.devices.createProject?.(owner,deviceId,"First");
  const get=await f.route("/devices");
  assert.equal(get?.status,200);
  const html=await get!.text();
  const csrf=/<form action="\/devices\/projects\/rename" method="post">[\s\S]*?name="csrf" value="([^"]+)"/.exec(html)?.[1];
  assert.ok(csrf);
  const cookie=get!.headers.get("set-cookie")?.split(";")[0]??"";
  const renamed=await f.route("/devices/projects/rename",ownerPost(
    "/devices/projects/rename",{project_id:projectId,alias:"Yeni Proje",csrf},cookie
  ));
  assert.equal(renamed?.status,303);
  assert.equal(f.getName(),"Yeni Proje");
  assert.equal(f.bindings(),0);
});

test("project names accept ordinary Unicode folder names, reject markup and traversal",()=>{
  for(const name of ["Motor-Board","\u015Eema 2026","KiCad (Rev A)","Board_1"]){
    assert.equal(validProjectAlias(name),true,name);
  }
  for(const name of ["../secret","<script>","\\device"," A","a/b","","x".repeat(70)]){
    assert.equal(validProjectAlias(name),false,name);
  }
});

test("two .kicad_pro files in one selected folder are separate project choices",()=>{
  const folder={status:"selected" as const,name:"Circuit Family",folderId:"token-A",
    projects:[{id:"token-A",name:"MainBoard"},{id:"token-B",name:"Antenna"}]};
  const html=renderLocalFolderPage(deviceId,folder,[
    {id:"token-A",name:"MainBoard",csrf:"csrf-A"},
    {id:"token-B",name:"Antenna",csrf:"csrf-B"}
  ]);
  assert.match(html,/multiple KiCad projects/i);
  assert.match(html,/MainBoard.kicad_pro/);
  assert.match(html,/Antenna.kicad_pro/);
  assert.equal((html.match(/action="\/devices\/projects\/select"/g)||[]).length,2);
  assert.match(html,/value="token-A"/);
  assert.match(html,/value="token-B"/);
  assert.match(html,/value="MainBoard"/);
  assert.match(html,/value="Antenna"/);
  assert.doesNotMatch(html,/C:\\Users\\|folder-browser-list/);
});

test("production owner browses remote KiCad directory and saves Cloud binding",async()=>{
  const f=fixture(false);
  const view=await beginSelection(f);
  assert.equal(view?.status,200);
  assert.equal(f.chooserCalls(),0,"remote browser must not open a native device picker");
  const html=await view!.text();
  assert.match(html,/This computer/);
  assert.match(html,new RegExp(folderName));
  assert.match(html,/action="\/devices\/projects\/folders"/);
  assert.doesNotMatch(html,/C:\\Users\\|\.kicad_sch/);
  const select=html.slice(html.indexOf('action="/devices/projects/select"'));
  assert.ok(select.length>0);
  const proof=/name="csrf" value="([^"]+)"/.exec(select)?.[1];
  assert.ok(proof,"selected remote folder needs owner-bound CSRF");
  const cookie=view!.headers.get("set-cookie")?.split(";")[0]??"";
  const result=await f.route("/devices/projects/select",ownerPost(
    "/devices/projects/select",{device_id:deviceId,folder_id:folderToken,
      alias:folderName,csrf:proof},cookie));
  assert.equal(result?.status,303);
  assert.equal(f.bindings(),1);
  assert.equal(f.getName(),folderName);
  assert.equal(f.removed(),0);
});

test("remote browser rejects paths, forged origin and unknown folder tokens",async()=>{
  const f=fixture(false);
  const view=await beginSelection(f);
  assert.equal(view?.status,200);
  const html=await view!.text();
  const folderForm=html.slice(html.indexOf('action="/devices/projects/folders"'));
  const proof=/name="csrf" value="([^"]+)"/.exec(folderForm)?.[1];
  assert.ok(proof);
  const cookie=view!.headers.get("set-cookie")?.split(";")[0]??"";
  const forged=await f.route("/devices/projects/folders",ownerPost(
    "/devices/projects/folders",{device_id:deviceId,folder_id:folderToken,
      csrf:proof},cookie,"https://attacker.invalid"));
  assert.equal(forged?.status,403);
  const path=await f.route("/devices/projects/folders",ownerPost(
    "/devices/projects/folders",{device_id:deviceId,
      folder_id:"C:\\Users\\Secret",csrf:proof},cookie));
  assert.equal(path?.status,400);
  assert.equal(f.bindings(),0);
});
