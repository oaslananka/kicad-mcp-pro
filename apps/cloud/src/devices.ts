import {randomBytes,timingSafeEqual} from "node:crypto";
import {makeSignature} from "better-auth/crypto";
import type {BrowserIdentity} from "./browser.js";
import type {PgDeviceManagement} from "./device-management.js";
import {renderDevicesPage} from "./devices-ui.js";
import {renderLocalFolderPage,renderRemoteFolderPage} from "./local-folder-page.js";
import {validProjectAlias} from "./device-management.js";
import type {LocalFolderPort} from "./connector-ws.js";
import type {GrantManagement,BrowserGrantSummary} from "./grants.js";
import type {PgManagedReadAccess} from "./connector-managed-read-access.js";

export type ManagedReadPort=Pick<PgManagedReadAccess,
  "enabledProjectIds"|"setEnabled"|"setNativeOperation"|"nativeOperationsByProject"|"isEnabled">;
export type DeviceConnectionLookup=(ownerSub:string,deviceId:string)=>boolean;
export type DeviceManagementPort=Pick<PgDeviceManagement,"list"|"revokeDevice"> &
  Partial<Pick<PgDeviceManagement,"deleteRevokedDevice"|"deleteProject">> &
  Partial<Pick<PgDeviceManagement,"enableDevice"|"createProject"|"listProjects"|"renameProject">>;
const FIVE_MINUTES=300_000;
const DEVICE_ID=/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
function cookieName(origin:string):string{
  return origin.startsWith("https://")?"__Host-kicad-devices":"kicad-devices";
}
function cookie(value:string,origin:string,age:number):string{
  return cookieName(origin)+"="+value+"; Path=/; HttpOnly; SameSite=Strict; Max-Age="+age+
    (origin.startsWith("https://")?"; Secure":"");
}
function readCookie(req:Request,origin:string):string|null{
  const name=cookieName(origin);
  return (req.headers.get("cookie")??"").split(";").map(x=>x.trim())
    .find(x=>x.startsWith(name+"="))?.slice(name.length+1)??null;
}
type DeviceReply={
  status:number;
  devices?:Parameters<typeof renderDevicesPage>[0];
  message?:string;
  stateCookie?:string;
  enrollmentAvailable?:boolean;
  projects?:Parameters<typeof renderDevicesPage>[3];
  ownerSub?:string;
  clients?:ReadonlyArray<string>;
  savedGrants?:ReadonlyArray<BrowserGrantSummary>;
  sandboxMode?:boolean;
  localFolders?:LocalFolderPort;
};
function reply({status,devices=[],message,stateCookie,enrollmentAvailable=true,
  projects=[],ownerSub,clients=[],savedGrants=[],sandboxMode=false,localFolders}:DeviceReply):Response{
  const response=new Response(renderDevicesPage(devices,message,enrollmentAvailable,projects,
    ownerSub,clients,savedGrants,sandboxMode,Boolean(localFolders)),{status,headers:{
    "Content-Type":"text/html; charset=utf-8","Cache-Control":"no-store",
    // Preserve Origin on same-origin form POSTs; Chrome sends Origin: null
    // under no-referrer. Cross-site referrers remain hidden.
    "Referrer-Policy":"same-origin","X-Content-Type-Options":"nosniff",
    "Content-Security-Policy":"default-src 'none'; base-uri 'none'; object-src 'none'; frame-ancestors 'none'; form-action 'self'; style-src 'self'; img-src 'self'; manifest-src 'self'; script-src 'self' https://static.cloudflareinsights.com; connect-src 'self' https://cloudflareinsights.com"
  }});
  if(stateCookie)response.headers.append("Set-Cookie",stateCookie);
  return response;
}
function error(status:number):Response{
  return reply({status,message:"Device management is temporarily unavailable.",enrollmentAvailable:false});
}
function pendingSchema(error:unknown):boolean{
  return Boolean(error && typeof error==="object" && "code" in error &&
    error.code==="42P01" && "message" in error &&
    typeof error.message==="string" && error.message.includes('"device_credentials"'));
}
function userOf(session:Awaited<ReturnType<NonNullable<BrowserIdentity["api"]>["getSession"]>>){
  if(!session?.user?.id||!session.session?.id)return null;
  return {user:session.user.id,session:session.session.id};
}
async function signature(secret:string,user:string,session:string,deviceId:string,stamp:string,nonce:string,
  purpose="device-revoke-v1"){
  const value=JSON.stringify([purpose,user,session,deviceId,stamp,nonce]);
  return Buffer.from(await makeSignature(value,secret),"base64").toString("base64url");
}
async function csrf(secret:string,user:string,session:string,deviceId:string,stamp:string,nonce:string,
  purpose="device-revoke-v1"){
  return stamp+"."+nonce+"."+(await signature(secret,user,session,deviceId,stamp,nonce,purpose));
}
async function checkCsrf(req:Request,origin:string,secret:string,
  owner:{user:string;session:string},id:string,sent:string,
  purpose="device-revoke-v1"):Promise<Response|null>{
  if(sent.length>250)return error(403);
  const [stamp,nonce,sig,...rest]=sent.split(".");
  if(rest.length||!/^\d{13}$/.test(stamp)||
    !/^[a-zA-Z0-9_-]{22}$/.test(nonce)||!/^[a-zA-Z0-9_-]{43}$/.test(sig))
    return error(403);
  const a=Buffer.from(await signature(secret,owner.user,owner.session,id,stamp,nonce,purpose));
  const b=Buffer.from(sig);
  if(a.length!==b.length||!timingSafeEqual(a,b))return error(403);
  const now=Date.now(),created=Number(stamp);
  if(created>now+5000)return error(403);
  // A real owner may leave this page open past cookie expiry. A signed stale
  // form is never executed, but may navigate to a freshly signed form.
  // Forged signatures, wrong sessions and future timestamps still get 403.
  if(now-created>FIVE_MINUTES)
    return new Response(null,{status:303,headers:{
      Location:"/devices?csrf=expired","Cache-Control":"no-store"
    }});
  if(readCookie(req,origin)!==stamp+"."+nonce)return error(403);
  return null;
}
async function list(req:Request,identity:BrowserIdentity,origin:string,
  devices:DeviceManagementPort,enrollmentAvailable=true,
  grants?:Pick<GrantManagement,"setBrowserGrant"|"listBrowserGrants">,
  deviceConnection?:DeviceConnectionLookup,managedRead?:ManagedReadPort,
  localFolders?:LocalFolderPort,nativeReadEnabled=false):Promise<Response>{
  if(!identity.api||!identity.$context)return error(503);
  const who=userOf(await identity.api.getSession({headers:req.headers}));
  if(!who)return new Response(null,{status:303,headers:{"Location":"/sign-in","Cache-Control":"no-store"}});
  let list:Awaited<ReturnType<DeviceManagementPort["list"]>>;
  try{list=await devices.list(who.user);}
  catch(cause){
    // Production intentionally remains below device-credential migration 008.
    // Show a clearly disabled page; never claim an empty live inventory.
    if(pendingSchema(cause))return reply({status:200,enrollmentAvailable:false});
    return error(503);
  }
  const {secret}=await identity.$context;
  const stamp=String(Date.now()),nonce=randomBytes(16).toString("base64url");
  const rows=await Promise.all(list.map(async d=>({...d,
    csrf:await csrf(secret,who.user,who.session,d.id,stamp,nonce),
    deleteCsrf:d.revoked&&devices.deleteRevokedDevice?
      await csrf(secret,who.user,who.session,d.id,stamp,nonce,"device-delete-v1"):undefined,
    enableCsrf:devices.enableDevice?
      await csrf(secret,who.user,who.session,d.id,stamp,nonce,"device-enable-v1"):undefined,
    projectCsrf:devices.createProject?
      await csrf(secret,who.user,who.session,d.id,stamp,nonce,"project-create-v1"):undefined,
    browseCsrf:identity.api&&localFolders&&d.enabled&&!d.revoked&&
      (identity.localDevSandbox||deviceConnection?.(who.user,d.id))?
      await csrf(secret,who.user,who.session,d.id,stamp,nonce,"project-native-picker-open-v1"):
      undefined,
    connectionState: deviceConnection&&d.enabled&&!d.revoked?
      (deviceConnection(who.user,d.id)?"connected" as const:"disconnected" as const):undefined
  })));
  const url=new URL(req.url);
  const access=url.searchParams.get("access");
  const note=url.searchParams.get("csrf")==="expired"?
    "The form expired while you were reviewing it. No permissions were changed. Review the action and try again.":
    url.searchParams.get("picker")==="unavailable"?
    "This device could not complete folder selection. Wait until it is Online and try Browse again.":
    url.searchParams.get("picker")==="cancelled"?
    "Folder selection cancelled. No project was added.":
    url.searchParams.get("picker")==="invalid"?
    "That folder does not contain a KiCad project (.kicad_pro). Select the project folder.":
    url.searchParams.has("project-removed")?
    "Project removed from Cloud. Its saved AI app permissions were deleted; local files are untouched.":
    url.searchParams.has("deleted")?
    "Revoked device and its registered projects were permanently removed.":
    url.searchParams.has("revoked")?
      "Device revoked. Its sessions and project access were disabled.":
    access==="granted"?"Project summary access was granted to the selected AI app.":
    access==="removed"?"The selected AI app's project access was removed.":
    access==="reads-on"?"Project summary access was enabled.":
    access==="reads-off"?"Project summary access was paused.":
    access==="native-on"?"This read-only KiCad diagnostic was enabled.":
    access==="native-off"?"This read-only KiCad diagnostic was disabled.":undefined;
  const projects=devices.listProjects?
    await devices.listProjects(who.user):[];
  let clients:string[]=[];
  if(enrollmentAvailable&&grants?.setBrowserGrant&&identity.api.getOAuthConsents){
    try{
      const consents=await identity.api.getOAuthConsents({headers:req.headers});
      if(Array.isArray(consents)){
        clients=[...new Set(consents.filter(c=>c.userId===who.user&&
          typeof c.clientId==="string"&&c.clientId.length<=1024&&
          Array.isArray(c.scopes)&&c.scopes.includes("projects:read"))
          .map(c=>c.clientId))].slice(0,100);
      }
    }catch{return error(503);}
  }
  // Never present a failed policy lookup as "no saved permissions".
  let savedGrants:BrowserGrantSummary[]=[];
  if(enrollmentAvailable&&grants?.listBrowserGrants){
    try{savedGrants=await grants.listBrowserGrants(who.user);}
    catch{return error(503);}
  }
  const managedIds=new Set(managedRead?await managedRead.enabledProjectIds(who.user):[]);
  const nativeRows=managedRead&&nativeReadEnabled?
    await managedRead.nativeOperationsByProject(who.user):[];
  const nativeByProject=new Map(nativeRows.map(row=>[row.projectId,row.operations]));
  // Only one local RPC may be outstanding on a signed Connector socket.
  // Serialize path lookups so every project in a multi-project folder gets
  // its own accurate path rather than an intermittent "unavailable".
  const localPaths=new Map<string,string>();
  if(identity.localDevSandbox&&localFolders&&
     url.searchParams.get("csrf-refresh")!=="1"){
    for(const project of projects){
      const value=await localFolders.getProjectPath(who.user,project.deviceId,project.id);
      if(value)localPaths.set(project.id,value);
    }
  }
  const scoped=await Promise.all(projects.map(async project=>({...project,
    localPath:localPaths.get(project.id),
    deleteCsrf:devices.deleteProject?
      await csrf(secret,who.user,who.session,project.id,stamp,nonce,"project-delete-v1"):undefined,
    renameCsrf:devices.renameProject?
      await csrf(secret,who.user,who.session,project.id,stamp,nonce,"project-rename-v1"):undefined,
    managedEnabled:managedRead?managedIds.has(project.id):undefined,
    nativeEnabled:nativeReadEnabled?nativeByProject.get(project.id)??[]:undefined,
    nativeCsrf:nativeReadEnabled&&managedRead?
      await csrf(secret,who.user,who.session,project.id,stamp,nonce,"project-managed-native-v1"):undefined,
    managedCsrf:managedRead?
      await csrf(secret,who.user,who.session,project.id,stamp,nonce,"project-managed-read-v1"):undefined,
    grantCsrf:grants?.setBrowserGrant?
      await csrf(secret,who.user,who.session,project.id,stamp,nonce,"project-browser-grant-v1"):
      undefined
  })));
  return reply({status:200,devices:rows,message:note,
    stateCookie:cookie(stamp+"."+nonce,origin,300),enrollmentAvailable,
    projects:scoped,ownerSub:who.user,clients,savedGrants,
    sandboxMode:identity.localDevSandbox===true,localFolders});
}
async function revoke(req:Request,identity:BrowserIdentity,origin:string,
  devices:DeviceManagementPort):Promise<Response>{
  if(!identity.api||!identity.$context)return error(503);
  if(req.headers.get("origin")!==origin)return error(403);
  if(req.headers.get("content-type")?.split(";")[0].trim()!=="application/x-www-form-urlencoded")
    return error(415);
  const raw=await req.text();
  if(raw.length>2048)return error(413);
  const fields=new URLSearchParams(raw);
  if(Array.from(fields.keys()).length!==2||
    fields.getAll("device_id").length!==1||fields.getAll("csrf").length!==1)return error(400);
  const id=fields.get("device_id")??"",proof=fields.get("csrf")??"";
  if(!DEVICE_ID.test(id))return error(400);
  const who=userOf(await identity.api.getSession({headers:req.headers}));
  if(!who)return error(401);
  const {secret}=await identity.$context;
  const csrfIssue=await checkCsrf(req,origin,secret,who,id,proof);
  if(csrfIssue)return csrfIssue;
  let success:boolean;
  try{success=await devices.revokeDevice(who.user,id);}
  catch{return error(503);}
  if(!success)return error(404);
  return new Response(null,{status:303,headers:{
    "Location":"/devices?revoked=1","Cache-Control":"no-store",
    "Set-Cookie":cookie("",origin,0)
  }});
}
async function deleteRevoked(req:Request,identity:BrowserIdentity,origin:string,
  devices:DeviceManagementPort):Promise<Response>{
  if(!identity.api||!identity.$context||!devices.deleteRevokedDevice)return error(503);
  if(req.headers.get("origin")!==origin)return error(403);
  if(req.headers.get("content-type")?.split(";")[0].trim()!=="application/x-www-form-urlencoded")
    return error(415);
  const raw=await req.text();
  if(raw.length>2048)return error(413);
  const fields=new URLSearchParams(raw);
  if([...fields.keys()].length!==2||
    fields.getAll("device_id").length!==1||fields.getAll("csrf").length!==1)return error(400);
  const id=fields.get("device_id")??"",proof=fields.get("csrf")??"";
  if(!DEVICE_ID.test(id))return error(400);
  const who=userOf(await identity.api.getSession({headers:req.headers}));
  if(!who)return error(401);
  const {secret}=await identity.$context;
  const csrfIssue=await checkCsrf(req,origin,secret,who,id,proof,"device-delete-v1");
  if(csrfIssue)return csrfIssue;
  let success:boolean;
  try{success=await devices.deleteRevokedDevice(who.user,id);}
  catch{return error(503);}
  if(!success)return error(404);
  return new Response(null,{status:303,headers:{
    Location:"/devices?deleted=1","Cache-Control":"no-store",
    "Set-Cookie":cookie("",origin,0)
  }});
}

async function deleteProject(req:Request,identity:BrowserIdentity,origin:string,
  devices:DeviceManagementPort):Promise<Response>{
  if(!identity.api||!identity.$context||!devices.deleteProject)return error(503);
  if(req.headers.get("origin")!==origin)return error(403);
  if(req.headers.get("content-type")?.split(";")[0].trim()!=="application/x-www-form-urlencoded")
    return error(415);
  const raw=await req.text();
  if(raw.length>2048)return error(413);
  const fields=new URLSearchParams(raw);
  if([...fields.keys()].length!==2||
    fields.getAll("project_id").length!==1||fields.getAll("csrf").length!==1)return error(400);
  const id=fields.get("project_id")??"",proof=fields.get("csrf")??"";
  if(!DEVICE_ID.test(id))return error(400);
  const who=userOf(await identity.api.getSession({headers:req.headers}));
  if(!who)return error(401);
  const {secret}=await identity.$context;
  const csrfIssue=await checkCsrf(req,origin,secret,who,id,proof,"project-delete-v1");
  if(csrfIssue)return csrfIssue;
  let success:boolean;
  try{success=await devices.deleteProject(who.user,id);}
  catch{return error(503);}
  if(!success)return error(404);
  return new Response(null,{status:303,headers:{
    Location:"/devices?project-removed=1","Cache-Control":"no-store",
    "Set-Cookie":cookie("",origin,0)
  }});
}

async function activate(req:Request,identity:BrowserIdentity,origin:string,
  devices:DeviceManagementPort,action:"device-enable-v1"|"project-create-v1"):Promise<Response>{
  if(!identity.api||!identity.$context)return error(503);
  if(req.headers.get("origin")!==origin)return error(403);
  if(req.headers.get("content-type")?.split(";")[0].trim()!=="application/x-www-form-urlencoded")
    return error(415);
  const raw=await req.text();
  if(raw.length>2048)return error(413);
  const fields=new URLSearchParams(raw);
  const expected=action==="device-enable-v1"?["device_id","csrf"]:
    ["device_id","csrf","alias"];
  if([...fields.keys()].length!==expected.length||
    expected.some(name=>fields.getAll(name).length!==1))return error(400);
  const id=fields.get("device_id")??"",proof=fields.get("csrf")??"";
  if(!DEVICE_ID.test(id))return error(400);
  const who=userOf(await identity.api.getSession({headers:req.headers}));
  if(!who)return error(401);
  const {secret}=await identity.$context;
  const csrfIssue=await checkCsrf(req,origin,secret,who,id,proof,action);
  if(csrfIssue)return csrfIssue;
  let success=false;
  try{
    if(action==="device-enable-v1"){
      success=!!await devices.enableDevice?.(who.user,id);
    }else{
      const alias=fields.get("alias")??"";
      if(!validProjectAlias(alias))return error(400);
      success=!!await devices.createProject?.(who.user,id,alias);
    }
  }catch{return error(503);}
  if(!success)return error(404);
  return new Response(null,{status:303,headers:{
    Location:"/devices", "Cache-Control":"no-store",
    "Set-Cookie":cookie("",origin,0)
  }});
}

async function ownerGrant(req:Request,identity:BrowserIdentity,origin:string,
  grants:Pick<GrantManagement,"setBrowserGrant">):Promise<Response>{
  if(!identity.api||!identity.$context||!grants.setBrowserGrant)return error(503);
  if(req.headers.get("origin")!==origin)return error(403);
  if(req.headers.get("content-type")?.split(";")[0].trim()!=="application/x-www-form-urlencoded")
    return error(415);
  const raw=await req.text();
  if(raw.length>2048)return error(413);
  const fields=new URLSearchParams(raw);
  const names=["project_id","client_id","enabled","csrf"];
  if([...fields.keys()].length!==names.length||
    names.some(name=>fields.getAll(name).length!==1))return error(400);
  const project=fields.get("project_id")??"",client=fields.get("client_id")??"";
  const enabled=fields.get("enabled"),proof=fields.get("csrf")??"";
  if(!DEVICE_ID.test(project)||!client||client.length>1024||
    (enabled!=="true"&&enabled!=="false"))return error(400);
  const who=userOf(await identity.api.getSession({headers:req.headers}));
  if(!who)return error(401);
  const {secret}=await identity.$context;
  const csrfIssue=await checkCsrf(req,origin,secret,who,project,proof,"project-browser-grant-v1");
  if(csrfIssue)return csrfIssue;
  let updated=false;
  try{updated=await grants.setBrowserGrant(who.user,project,client,enabled==="true");}
  catch{return error(503);}
  if(!updated)return error(404);
  return new Response(null,{status:303,headers:{
    Location:enabled==="true"?"/devices?access=granted":"/devices?access=removed",
    "Cache-Control":"no-store","Set-Cookie":cookie("",origin,0)}});
}


async function ownerManagedRead(req:Request,identity:BrowserIdentity,origin:string,
  managedRead:ManagedReadPort):Promise<Response>{
  if(!identity.api||!identity.$context)return error(503);
  if(req.headers.get("origin")!==origin)return error(403);
  if(req.headers.get("content-type")?.split(";")[0].trim()!=="application/x-www-form-urlencoded")
    return error(415);
  const raw=await req.text();
  if(raw.length>2048)return error(413);
  const fields=new URLSearchParams(raw);
  const names=["project_id","device_id","enabled","csrf"];
  if([...fields.keys()].length!==names.length||
    names.some(name=>fields.getAll(name).length!==1))return error(400);
  const project=fields.get("project_id")??"",device=fields.get("device_id")??"";
  const enabled=fields.get("enabled"),proof=fields.get("csrf")??"";
  if(!DEVICE_ID.test(project)||!DEVICE_ID.test(device)||
    (enabled!=="true"&&enabled!=="false"))return error(400);
  const who=userOf(await identity.api.getSession({headers:req.headers}));
  if(!who)return error(401);
  const {secret}=await identity.$context;
  const csrfIssue=await checkCsrf(req,origin,secret,who,project,proof,"project-managed-read-v1");
  if(csrfIssue)return csrfIssue;
  let updated:boolean;
  try{updated=await managedRead.setEnabled(who.user,device,project,enabled==="true");}
  catch{return error(503);}
  if(!updated)return error(404);
  return new Response(null,{status:303,headers:{
    Location:enabled==="true"?"/devices?access=reads-on":"/devices?access=reads-off",
    "Cache-Control":"no-store","Set-Cookie":cookie("",origin,0)}});
}




/** Web navigation asks a signed owner device for opaque folder tokens only. */
async function showRemoteFolders(identity:BrowserIdentity,origin:string,
  folders:LocalFolderPort,who:NonNullable<ReturnType<typeof userOf>>,
  device:string,folderId:string):Promise<Response>{
  if(!identity.$context)return error(503);
  const listing=await folders.listFolder(who.user,device,folderId);
  if(!listing)return new Response(null,{status:303,headers:{
    Location:"/devices?picker=unavailable","Cache-Control":"no-store"}});
  const {secret}=await identity.$context;
  const stamp=String(Date.now()),nonce=randomBytes(16).toString("base64url");
  const key=(folder:string)=>device+":"+folder;
  const openToken=(folder:string)=>csrf(secret,who.user,who.session,key(folder),
    stamp,nonce,"project-folder-open-v1");
  const selectToken=(folder:string)=>csrf(secret,who.user,who.session,key(folder),
    stamp,nonce,"project-folder-select-v1");
  const choices=await Promise.all(listing.folders.map(async entry=>({
    id:entry.id,name:entry.name,project:entry.project,
    openCsrf:await openToken(entry.id),
    ...(entry.project?{selectCsrf:await selectToken(entry.id)}:{})
  })));
  const current=listing.project?await selectToken(listing.folderId):undefined;
  const parent=listing.parentId?await openToken(listing.parentId):undefined;
  return new Response(renderRemoteFolderPage(device,listing,choices,current,parent),{
    status:200,headers:{
      "Content-Type":"text/html; charset=utf-8","Cache-Control":"no-store",
      "Set-Cookie":cookie(stamp+"."+nonce,origin,300),
      "Referrer-Policy":"same-origin","X-Content-Type-Options":"nosniff",
      "Content-Security-Policy":"default-src 'none'; style-src 'self'; img-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
    }
  });
}

async function folderOpen(req:Request,identity:BrowserIdentity,origin:string,
  devices:DeviceManagementPort,folders?:LocalFolderPort):Promise<Response>{
  if(!folders||!identity.api||!identity.$context)return error(404);
  if(req.headers.get("origin")!==origin)return error(403);
  if(req.headers.get("content-type")?.split(";")[0].trim()!=="application/x-www-form-urlencoded")
    return error(415);
  const raw=await req.text();
  if(raw.length>750)return error(413);
  const fields=new URLSearchParams(raw);
  if([...fields.keys()].length!==3||
     ["device_id","folder_id","csrf"].some(x=>fields.getAll(x).length!==1))
    return error(400);
  const device=fields.get("device_id")??"",folder=fields.get("folder_id")??"";
  if(!DEVICE_ID.test(device)||!/^[A-Za-z0-9_-]{1,64}$/.test(folder))return error(400);
  const who=userOf(await identity.api.getSession({headers:req.headers}));
  if(!who)return error(401);
  const {secret}=await identity.$context;
  const check=await checkCsrf(req,origin,secret,who,device+":"+folder,
    fields.get("csrf")??"","project-folder-open-v1");
  if(check)return check;
  const own=await devices.list(who.user);
  if(!own.some(d=>d.id===device&&d.enabled&&!d.revoked))return error(404);
  return showRemoteFolders(identity,origin,folders,who,device,folder);
}
/** Local-dev native picker, or production web folder browser. */
async function folderBrowse(req:Request,identity:BrowserIdentity,origin:string,
  devices:DeviceManagementPort,folders?:LocalFolderPort):Promise<Response>{
  if(!folders||!identity.api||!identity.$context)return error(404);
  if(req.headers.get("origin")!==origin)return error(403);
  if(req.headers.get("content-type")?.split(";")[0].trim()!=="application/x-www-form-urlencoded")
    return error(415);
  const raw=await req.text();
  if(raw.length>750)return error(413);
  const fields=new URLSearchParams(raw);
  if([...fields.keys()].length!==2||
     ["device_id","csrf"].some(x=>fields.getAll(x).length!==1))return error(400);
  const device=fields.get("device_id")??"";
  if(!DEVICE_ID.test(device))return error(400);
  const who=userOf(await identity.api.getSession({headers:req.headers}));
  if(!who)return error(401);
  const {secret}=await identity.$context;
  const csrfIssue=await checkCsrf(req,origin,secret,who,device,fields.get("csrf")??"",
    "project-native-picker-open-v1");
  if(csrfIssue)return csrfIssue;
  const own=await devices.list(who.user);
  if(!own.some(d=>d.id===device&&d.enabled&&!d.revoked))return error(404);

  // In production the browser browses the selected signed remote device.
  // Never open a native modal on someone else's monitor.
  if(!identity.localDevSandbox)
    return showRemoteFolders(identity,origin,folders,who,device,"root");
  const selection=await folders.chooseFolder(who.user,device);
  if(!selection)return new Response(null,{status:303,headers:{
    Location:"/devices?picker=unavailable","Cache-Control":"no-store"
  }});
  if(selection.status==="cancelled"||selection.status==="invalid"){
    return new Response(null,{status:303,headers:{
      "Location":selection.status==="cancelled"?"/devices?picker=cancelled":
        "/devices?picker=invalid","Cache-Control":"no-store"
    }});
  }
  if(selection.status!=="selected"||!selection.folderId||!selection.name||
     !selection.projects?.length)return error(503);
  const stamp=String(Date.now()),nonce=randomBytes(16).toString("base64url");
  const choices=await Promise.all(selection.projects.map(async project=>({
    ...project,csrf:await csrf(secret,who.user,who.session,
      device+":"+project.id,stamp,nonce,"project-folder-select-v1")
  })));
  return new Response(renderLocalFolderPage(device,selection,choices),{
    status:200,headers:{
      "Content-Type":"text/html; charset=utf-8","Cache-Control":"no-store",
      "Set-Cookie":cookie(stamp+"."+nonce,origin,300),
      "Referrer-Policy":"same-origin",
      "X-Content-Type-Options":"nosniff",
      "Content-Security-Policy":"default-src 'none'; style-src 'self'; img-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
    }
  });
}

/** Local selection is atomic from the user's perspective: persist Cloud label
 * only after a real signed device has confirmed this actual KiCad folder. */
async function folderSelect(req:Request,identity:BrowserIdentity,origin:string,
  devices:DeviceManagementPort,folders?:LocalFolderPort):Promise<Response>{
  if(!folders||!identity.api||!identity.$context||
     !devices.createProject||!devices.deleteProject)return error(404);
  if(req.headers.get("origin")!==origin)return error(403);
  if(req.headers.get("content-type")?.split(";")[0].trim()!=="application/x-www-form-urlencoded")
    return error(415);
  const raw=await req.text();
  if(raw.length>2048)return error(413);
  const fields=new URLSearchParams(raw);
  if([...fields.keys()].length!==4||
     ["device_id","folder_id","alias","csrf"].some(x=>fields.getAll(x).length!==1))return error(400);
  const device=fields.get("device_id")??"",folder=fields.get("folder_id")??"";
  const alias=(fields.get("alias")??"").trim();
  if(!DEVICE_ID.test(device)||folder.length<1||folder.length>64||
     !validProjectAlias(alias))return error(400);
  const who=userOf(await identity.api.getSession({headers:req.headers}));
  if(!who)return error(401);
  const {secret}=await identity.$context;
  const csrfIssue=await checkCsrf(req,origin,secret,who,device+":"+folder,
    fields.get("csrf")??"","project-folder-select-v1");
  if(csrfIssue)return csrfIssue;
  const own=await devices.list(who.user);
  if(!own.some(d=>d.id===device&&d.enabled&&!d.revoked))return error(404);
  const listing=await folders.listFolder(who.user,device,folder);
  if(!listing?.project)return error(422);
  const newId=await devices.createProject(who.user,device,alias);
  if(!newId)return error(409);
  let accepted=false;
  try{accepted=await folders.bindFolder(who.user,device,folder,newId);}
  catch{accepted=false;}
  if(!accepted){
    await devices.deleteProject(who.user,newId);
    return error(503);
  }
  return new Response(null,{status:303,headers:{
    Location:"/devices#registered-projects","Cache-Control":"no-store",
    "Set-Cookie":cookie("",origin,0)
  }});
}
async function projectRename(req:Request,identity:BrowserIdentity,origin:string,
  devices:DeviceManagementPort):Promise<Response>{
  if(!identity.api||!identity.$context||!devices.renameProject)return error(404);
  if(req.headers.get("origin")!==origin)return error(403);
  if(req.headers.get("content-type")?.split(";")[0].trim()!=="application/x-www-form-urlencoded")
    return error(415);
  const raw=await req.text();
  if(raw.length>1024)return error(413);
  const fields=new URLSearchParams(raw);
  if([...fields.keys()].length!==3||
    ["project_id","alias","csrf"].some(x=>fields.getAll(x).length!==1))return error(400);
  const projectId=fields.get("project_id")??"";
  const alias=(fields.get("alias")??"").trim();
  if(!DEVICE_ID.test(projectId)||!validProjectAlias(alias))return error(400);
  const who=userOf(await identity.api.getSession({headers:req.headers}));
  if(!who)return error(401);
  const {secret}=await identity.$context;
  const csrfIssue=await checkCsrf(req,origin,secret,who,projectId,fields.get("csrf")??"",
     "project-rename-v1");
  if(csrfIssue)return csrfIssue;
  try{
    if(!await devices.renameProject(who.user,projectId,alias))return error(404);
  }catch{return error(503);}
  return new Response(null,{status:303,headers:{
    Location:"/devices#registered-projects","Cache-Control":"no-store",
    "Set-Cookie":cookie("",origin,0)
  }});
}


// Only native DRC is implemented by the current owner-managed Windows worker.
// Keep other diagnostic grants unavailable until their device-side acceptance passes.
const MANAGED_NATIVE_OPERATIONS=["run_drc"] as const;
type ManagedNativeOperation=(typeof MANAGED_NATIVE_OPERATIONS)[number];
function managedNativeOperation(value:string|null):value is ManagedNativeOperation{
  return MANAGED_NATIVE_OPERATIONS.some(operation=>operation===value);
}

/** This form cannot be submitted by AI clients or from a foreign origin. */
async function ownerManagedNativeRead(req:Request,identity:BrowserIdentity,origin:string,
  managedRead:ManagedReadPort):Promise<Response>{
  if(!identity.api||!identity.$context)return error(503);
  if(req.headers.get("origin")!==origin)return error(403);
  if(req.headers.get("content-type")?.split(";")[0].trim()!=="application/x-www-form-urlencoded")
    return error(415);
  const raw=await req.text();
  if(raw.length>2048)return error(413);
  const fields=new URLSearchParams(raw);
  const names=["project_id","device_id","operation","enabled","csrf"];
  if([...fields.keys()].length!==names.length||
    names.some(name=>fields.getAll(name).length!==1))return error(400);
  const project=fields.get("project_id")??"",device=fields.get("device_id")??"";
  const operation=fields.get("operation"),enabled=fields.get("enabled");
  const proof=fields.get("csrf")??"";
  if(!DEVICE_ID.test(project)||!DEVICE_ID.test(device)||
    !managedNativeOperation(operation)||(enabled!=="true"&&enabled!=="false"))
    return error(400);
  const who=userOf(await identity.api.getSession({headers:req.headers}));
  if(!who)return error(401);
  const {secret}=await identity.$context;
  const csrfIssue=await checkCsrf(req,origin,secret,who,project,proof,
    "project-managed-native-v1");
  if(csrfIssue)return csrfIssue;
  let updated:boolean;
  try{updated=await managedRead.setNativeOperation(
    who.user,device,project,operation,enabled==="true");}
  catch{return error(503);}
  if(!updated)return error(404);
  return new Response(null,{status:303,headers:{
    Location:enabled==="true"?"/devices?access=native-on":"/devices?access=native-off",
    "Cache-Control":"no-store","Set-Cookie":cookie("",origin,0)}});
}

/** Authenticated browser-only management, never usable in external auth mode. */
export async function devicesResponse(req:Request,identity:BrowserIdentity,origin:string,
  devices?:DeviceManagementPort,enrollmentAvailable=true,
  grants?:Pick<GrantManagement,"setBrowserGrant"|"listBrowserGrants">,
  deviceConnection?:DeviceConnectionLookup,managedRead?:ManagedReadPort,
  localFolders?:LocalFolderPort,nativeReadEnabled=false):Promise<Response|null>{
  const path=new URL(req.url).pathname;
  if(!["/devices","/devices/revoke","/devices/delete","/devices/enable","/devices/projects/create",
    "/devices/projects/grant","/devices/projects/managed","/devices/projects/native","/devices/projects/delete",
    "/devices/projects/browse","/devices/projects/folders","/devices/projects/select","/devices/projects/rename"].includes(path))
    return null;
  if(!devices)return error(503);
  // A direct navigation is never a removal command. Keep users in the
  // authenticated device list rather than rendering an unhelpful JSON 404.
  if(path==="/devices/delete"&&req.method==="GET")
    return new Response(null,{status:303,headers:{
      Location:"/devices","Cache-Control":"no-store"
    }});
  if(path==="/devices"&&req.method==="GET")
    return list(req,identity,origin,devices,enrollmentAvailable,grants,deviceConnection,
      managedRead,localFolders,nativeReadEnabled);
  if(path==="/devices/revoke"&&req.method==="POST")return revoke(req,identity,origin,devices);
  if(path==="/devices/delete"&&req.method==="POST")
    return deleteRevoked(req,identity,origin,devices);
  if(path==="/devices/projects/delete"&&req.method==="POST")
    return deleteProject(req,identity,origin,devices);
  if(path==="/devices/projects/browse"&&req.method==="POST")
    return folderBrowse(req,identity,origin,devices,localFolders);
  if(path==="/devices/projects/browse"&&req.method==="GET")
    return new Response(null,{status:303,headers:{
      Location:"/devices","Cache-Control":"no-store"
    }});
  if(path==="/devices/projects/folders"&&req.method==="POST")
    return folderOpen(req,identity,origin,devices,localFolders);
  if(path==="/devices/projects/select"&&req.method==="POST")
    return folderSelect(req,identity,origin,devices,localFolders);
  if(path==="/devices/projects/rename"&&req.method==="POST")
    return projectRename(req,identity,origin,devices);
  if(enrollmentAvailable && req.method==="POST"){
    if(path==="/devices/enable")return activate(req,identity,origin,devices,"device-enable-v1");
    if(path==="/devices/projects/create")return activate(req,identity,origin,devices,"project-create-v1");
    if(path==="/devices/projects/grant"&&grants)return ownerGrant(req,identity,origin,grants);
    if(path==="/devices/projects/managed"&&managedRead)
      return ownerManagedRead(req,identity,origin,managedRead);
    if(path==="/devices/projects/native"&&managedRead&&nativeReadEnabled)
      return ownerManagedNativeRead(req,identity,origin,managedRead);
  }
  return error(405);
}
