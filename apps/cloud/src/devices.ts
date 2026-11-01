import {randomBytes,timingSafeEqual} from "node:crypto";
import {makeSignature} from "better-auth/crypto";
import type {BrowserIdentity} from "./browser.js";
import type {PgDeviceManagement} from "./device-management.js";
import {renderDevicesPage} from "./devices-ui.js";
import type {GrantManagement} from "./grants.js";

export type DeviceManagementPort=Pick<PgDeviceManagement,"list"|"revokeDevice"> &
  Partial<Pick<PgDeviceManagement,"enableDevice"|"createProject"|"listProjects">>;
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
  projects?:ReadonlyArray<{id:string;deviceId:string;alias:string;enabled:boolean;grantCsrf?:string}>;
  ownerSub?:string;
  clients?:ReadonlyArray<string>;
};
function reply({status,devices=[],message,stateCookie,enrollmentAvailable=true,
  projects=[],ownerSub,clients=[]}:DeviceReply):Response{
  const response=new Response(renderDevicesPage(devices,message,enrollmentAvailable,projects,ownerSub,clients),{status,headers:{
    "Content-Type":"text/html; charset=utf-8","Cache-Control":"no-store",
    // Preserve Origin on same-origin form POSTs; Chrome sends Origin: null
    // under no-referrer. Cross-site referrers remain hidden.
    "Referrer-Policy":"same-origin","X-Content-Type-Options":"nosniff",
    "Content-Security-Policy":"default-src 'none'; base-uri 'none'; object-src 'none'; frame-ancestors 'none'; form-action 'self'; style-src 'self'"
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
  purpose="device-revoke-v1"):Promise<boolean>{
  if(sent.length>250||!readCookie(req,origin))return false;
  const [stamp,nonce,sig,...rest]=sent.split(".");
  if(rest.length||!/^\d{13}$/.test(stamp)||
    !/^[a-zA-Z0-9_-]{22}$/.test(nonce)||!/^[a-zA-Z0-9_-]{43}$/.test(sig))return false;
  if(readCookie(req,origin)!==stamp+"."+nonce)return false;
  const now=Date.now(),created=Number(stamp);
  if(created>now+5000||now-created>FIVE_MINUTES)return false;
  const a=Buffer.from(await signature(secret,owner.user,owner.session,id,stamp,nonce,purpose));
  const b=Buffer.from(sig);
  return a.length===b.length&&timingSafeEqual(a,b);
}
async function list(req:Request,identity:BrowserIdentity,origin:string,
  devices:DeviceManagementPort,enrollmentAvailable=true,
  grants?:Pick<GrantManagement,"setBrowserGrant">):Promise<Response>{
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
    enableCsrf:devices.enableDevice?
      await csrf(secret,who.user,who.session,d.id,stamp,nonce,"device-enable-v1"):undefined,
    projectCsrf:devices.createProject?
      await csrf(secret,who.user,who.session,d.id,stamp,nonce,"project-create-v1"):undefined
  })));
  const note=new URL(req.url).searchParams.has("revoked")?
    "Device key revoked; its sessions and associated project/client permissions were disabled.":undefined;
  const projects=enrollmentAvailable&&devices.listProjects?
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
  const scoped=await Promise.all(projects.map(async project=>({...project,
    grantCsrf:grants?.setBrowserGrant?
      await csrf(secret,who.user,who.session,project.id,stamp,nonce,"project-browser-grant-v1"):
      undefined
  })));
  return reply({status:200,devices:rows,message:note,
    stateCookie:cookie(stamp+"."+nonce,origin,300),enrollmentAvailable,
    projects:scoped,ownerSub:who.user,clients});
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
  if(!await checkCsrf(req,origin,secret,who,id,proof))return error(403);
  let success:boolean;
  try{success=await devices.revokeDevice(who.user,id);}
  catch{return error(503);}
  if(!success)return error(404);
  return new Response(null,{status:303,headers:{
    "Location":"/devices?revoked=1","Cache-Control":"no-store",
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
  if(!await checkCsrf(req,origin,secret,who,id,proof,action))return error(403);
  let success=false;
  try{
    if(action==="device-enable-v1"){
      success=!!await devices.enableDevice?.(who.user,id);
    }else{
      const alias=fields.get("alias")??"";
      if(!/^[A-Za-z0-9][A-Za-z0-9 ._-]{0,63}$/.test(alias))return error(400);
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
  if(!await checkCsrf(req,origin,secret,who,project,proof,"project-browser-grant-v1"))
    return error(403);
  let updated=false;
  try{updated=await grants.setBrowserGrant(who.user,project,client,enabled==="true");}
  catch{return error(503);}
  if(!updated)return error(404);
  return new Response(null,{status:303,headers:{Location:"/devices",
    "Cache-Control":"no-store","Set-Cookie":cookie("",origin,0)}});
}

/** Authenticated browser-only management, never usable in external auth mode. */
export async function devicesResponse(req:Request,identity:BrowserIdentity,origin:string,
  devices?:DeviceManagementPort,enrollmentAvailable=true,
  grants?:Pick<GrantManagement,"setBrowserGrant">):Promise<Response|null>{
  const path=new URL(req.url).pathname;
  if(!["/devices","/devices/revoke","/devices/enable","/devices/projects/create",
    "/devices/projects/grant"].includes(path))
    return null;
  if(!devices)return error(503);
  if(path==="/devices"&&req.method==="GET")return list(req,identity,origin,devices,enrollmentAvailable,grants);
  if(path==="/devices/revoke"&&req.method==="POST")return revoke(req,identity,origin,devices);
  if(enrollmentAvailable && req.method==="POST"){
    if(path==="/devices/enable")return activate(req,identity,origin,devices,"device-enable-v1");
    if(path==="/devices/projects/create")return activate(req,identity,origin,devices,"project-create-v1");
    if(path==="/devices/projects/grant"&&grants)return ownerGrant(req,identity,origin,grants);
  }
  return error(405);
}
