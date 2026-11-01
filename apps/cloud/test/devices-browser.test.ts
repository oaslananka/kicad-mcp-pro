import assert from "node:assert/strict";
import {randomUUID} from "node:crypto";
import {test} from "node:test";
import {devicesResponse,type DeviceManagementPort} from "../src/devices.js";
import type {BrowserIdentity} from "../src/browser.js";

const origin="http://127.0.0.1:8787";
function fixture(user:string|null="owner-a"){
  const ownId=randomUUID(),otherId=randomUUID();
  const calls:string[]=[];
  const device={
    id:ownId,alias:"<script>malicious()</script> & Lab",
    enabled:true,revoked:false,fingerprint:"a".repeat(64),createdAt:new Date()
  };
  const identity={
    $context:Promise.resolve({secret:"test-only-device-secret-at-least-32-characters"}),
    api:{getSession:async()=>user?{session:{id:"browser-session-a"},user:{id:user}}:null},
    handler:async()=>new Response(null,{status:404})
  } as unknown as BrowserIdentity;
  const devices:DeviceManagementPort={
    async list(owner){
      calls.push("list:"+owner);
      return owner==="owner-a"?[device]:[];
    },
    async revokeDevice(owner,id){
      calls.push("revoke:"+owner+":"+id);
      return owner==="owner-a"&&id===ownId;
    }
  };
  return {identity,devices,ownId,otherId,calls};
}
async function view(f:ReturnType<typeof fixture>){
  return devicesResponse(new Request(origin+"/devices"),f.identity,origin,f.devices);
}
function csrf(html:string):string{
  return /name="csrf" value="([^"]+)"/.exec(html)?.[1]??"";
}
function submit(id:string,token:string,state:string,providedOrigin=origin,extra?:string){
  const payload=new URLSearchParams({device_id:id,csrf:token});
  if(extra)payload.append(extra,"injected");
  return new Request(origin+"/devices/revoke",{
    method:"POST",headers:{
      Origin:providedOrigin,"Content-Type":"application/x-www-form-urlencoded",
      Cookie:state
    },body:payload
  });
}
test("device owner listing requires a browser session and escapes device metadata",async()=>{
  const anonymous=await view(fixture(null));
  assert.equal(anonymous?.status,303);
  assert.equal(anonymous?.headers.get("location"),"/sign-in");
  const f=fixture();
  const page=await view(f);
  assert.equal(page?.status,200);
  const html=await page!.text();
  assert.match(html,/&lt;script&gt;/);
  assert.doesNotMatch(html,/<script>malicious/);
  assert.match(html,/not proof of online status/);
  assert.match(page!.headers.get("set-cookie")??"",/HttpOnly; SameSite=Strict/);
  assert.doesNotMatch(html,/secret|private_key|public_key_der/);
  assert.deepEqual(f.calls,["list:owner-a"]);
});
test("authenticated devices page reports only actual owner-bound connector sessions",async()=>{
  const f=fixture();
  const checks:string[]=[];
  const connected=(owner:string,device:string)=>{
    checks.push(owner+":"+device);
    return owner==="owner-a"&&device===f.ownId;
  };
  const page=await devicesResponse(
    new Request(origin+"/devices"),f.identity,origin,f.devices,true,undefined,connected);
  assert.equal(page?.status,200);
  const html=await page!.text();
  assert.match(html,/Connector connected now \(temporary session; not proof of KiCad activity\)/);
  assert.deepEqual(checks,["owner-a:"+f.ownId]);
  const offline=await devicesResponse(
    new Request(origin+"/devices"),f.identity,origin,f.devices,true,undefined,()=>false);
  assert.match(await offline!.text(),/Connector not connected now/);
  const anonymous=fixture(null);
  let called=false;
  const unauthenticated=await devicesResponse(
    new Request(origin+"/devices"),anonymous.identity,origin,anonymous.devices,true,
    undefined,()=>{called=true;return true;});
  assert.equal(unauthenticated?.status,303);
  assert.equal(called,false,"anonymous view must never query any device connection");
  const other=fixture("owner-b");
  const outsider=await devicesResponse(
    new Request(origin+"/devices"),other.identity,origin,other.devices,true,
    undefined,()=>{called=true;return true;});
  assert.equal(outsider?.status,200);
  assert.doesNotMatch(await outsider!.text(),/Connector connected now/);
  assert.equal(called,false,"foreign account cannot enumerate ready sockets");
});

test("valid owner-bound CSRF revokes exactly the selected device",async()=>{
  const f=fixture();
  const response=await view(f);
  const token=csrf(await response!.text());
  const cookie=(response!.headers.get("set-cookie")??"").split(";")[0];
  const revoked=await devicesResponse(
    submit(f.ownId,token,cookie),f.identity,origin,f.devices);
  assert.equal(revoked?.status,303);
  assert.equal(revoked?.headers.get("location"),"/devices?revoked=1");
  assert.deepEqual(f.calls,["list:owner-a","revoke:owner-a:"+f.ownId]);
});
test("cross-origin, malformed form, expired-cookie, forged identity and wrong device fail",async()=>{
  const f=fixture(),r=await view(f);
  const token=csrf(await r!.text()),cookie=(r!.headers.get("set-cookie")??"").split(";")[0];
  assert.equal((await devicesResponse(submit(f.ownId,token,cookie,"https://evil.invalid"),f.identity,origin,f.devices))?.status,403);
  assert.equal((await devicesResponse(submit(f.ownId,token,""),f.identity,origin,f.devices))?.status,403);
  assert.equal((await devicesResponse(submit(f.otherId,token,cookie),f.identity,origin,f.devices))?.status,403);
  assert.equal((await devicesResponse(submit(f.ownId,token,cookie,origin,"extra"),f.identity,origin,f.devices))?.status,400);
  const fakeUser=fixture("owner-b");
  assert.equal((await devicesResponse(submit(f.ownId,token,cookie),fakeUser.identity,origin,f.devices))?.status,403);
  assert.deepEqual(f.calls,["list:owner-a"]);
});
test("backend errors fail closed, unknown device identity remains indistinguishable",async()=>{
  const f=fixture();
  const response=await view(f);
  const token=csrf(await response!.text()),cookie=(response!.headers.get("set-cookie")??"").split(";")[0];
  const other:DeviceManagementPort={list:f.devices.list,
    revokeDevice:async()=>false};
  const denied=await devicesResponse(submit(f.ownId,token,cookie),f.identity,origin,other);
  assert.equal(denied?.status,404);
  const failing:DeviceManagementPort={list:f.devices.list,
    revokeDevice:async()=>{throw new Error("db disconnected");}};
  const failure=await devicesResponse(submit(f.ownId,token,cookie),f.identity,origin,failing);
  assert.equal(failure?.status,503);
  assert.doesNotMatch(await failure!.text(),/db disconnected/);
});
test("pre-enrollment production schema renders a disabled page without leaking database errors",async()=>{
  const f=fixture();
  const pending:DeviceManagementPort={...f.devices,
    list:async()=>{throw Object.assign(new Error('relation "device_credentials" does not exist'),{code:"42P01"});}
  };
  const response=await devicesResponse(new Request(origin+"/devices"),f.identity,origin,pending);
  assert.equal(response?.status,200);
  const html=await response!.text();
  assert.match(html,/not enabled on this deployment/);
  assert.doesNotMatch(html,/Review device pairing|device_credentials|relation.*does not exist/);
  assert.doesNotMatch(html,/<form action="\/devices\/revoke"/);
  const broken:DeviceManagementPort={...f.devices,
    list:async()=>{throw new Error("database disconnected - sensitive detail");}
  };
  const error=await devicesResponse(new Request(origin+"/devices"),f.identity,origin,broken);
  assert.equal(error?.status,503);
  assert.doesNotMatch(await error!.text(),/sensitive detail/);
});

test("no device manager cannot mutate devices",async()=>{
  const f=fixture(),r=await view(f);
  const token=csrf(await r!.text()),cookie=(r!.headers.get("set-cookie")??"").split(";")[0];
  assert.equal((await devicesResponse(submit(f.ownId,token,cookie),f.identity,origin))?.status,503);
});

test("schema-ready inventory remains disabled without explicitly enabled device pairing",async()=>{
  const empty=fixture("owner-b");
  const gated=await devicesResponse(new Request(origin+"/devices"),empty.identity,origin,empty.devices,false);
  assert.equal(gated?.status,200);
  const html=await gated!.text();
  assert.match(html,/not enabled on this deployment/);
  assert.doesNotMatch(html,/href="\/devices\/pairing"/);
  assert.doesNotMatch(html,/action="\/devices\/revoke"/);
  // Existing users must retain credential-revocation even if new enrollment
  // is disabled. Do not hide live devices behind a feature flag.
  const existing=fixture();
  const response=await devicesResponse(new Request(origin+"/devices"),existing.identity,origin,existing.devices,false);
  assert.equal(response?.status,200);
  const detail=await response!.text();
  assert.match(detail,/Revoke device/);
  assert.doesNotMatch(detail,/href="\/devices\/pairing"/);
});
