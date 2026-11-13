import assert from "node:assert/strict";
import {test} from "node:test";
import {cliApproveResponse,PgOwnerApiAccess} from "../src/owner-api.js";
import {browserResponse} from "../src/browser.js";
import type {BrowserIdentity} from "../src/browser.js";
import type {Pool} from "pg";

const origin="https://cloud.example.test";
const requestId="A".repeat(43);
const url=origin+"/api/owner/cli/approve?request_id="+requestId;

function fixture(){
  let approved=0;
  const ownerApi={
    getRequest:async(id:string)=>id===requestId?{state:"pending",label:"My device"}:null,
    approveRequest:async(owner:string,id:string)=>{
      if(owner!=="signed-in-owner"||id!==requestId)return false;
      approved++;
      return true;
    }
  } as unknown as PgOwnerApiAccess;
  const identity={
    api:{getSession:async({headers}:{headers:Headers})=>
      headers.get("cookie")?.includes("signed-in-owner")?
        {session:{id:"browser-session"},user:{id:"signed-in-owner"}}:null},
    $context:Promise.resolve({secret:"test-owner-cli-secret-longer-than-thirty-two-bytes"})
  } as unknown as BrowserIdentity;
  return {ownerApi,identity,approved:()=>approved};
}

test("owner-approved CLI access requires valid first-party double-submit CSRF",async()=>{
  const f=fixture();
  const page=await cliApproveResponse(new Request(url,{
    headers:{Cookie:"session=signed-in-owner"}
  }),f.identity,origin,f.ownerApi);
  assert.equal(page?.status,200);
  const html=await page!.text();
  assert.match(html,/Approve this computer/);
  const csrf=/name="csrf" value="([^"]+)"/.exec(html)?.[1];
  assert.ok(csrf);
  const proofCookie=page!.headers.get("set-cookie")?.split(";")[0];
  assert.match(proofCookie??"",/^__Host-kicad-cli-approve=/);
  const validHeaders={Origin:origin,"Content-Type":"application/x-www-form-urlencoded",
    Cookie:"session=signed-in-owner; "+proofCookie};
  const deny=await cliApproveResponse(new Request(url,{method:"POST",headers:{
    ...validHeaders,Origin:"https://attacker.invalid"
  },body:new URLSearchParams({csrf})}),f.identity,origin,f.ownerApi);
  assert.equal(deny?.status,403);
  assert.equal(f.approved(),0);
  const success=await cliApproveResponse(new Request(url,{method:"POST",
    headers:validHeaders,body:new URLSearchParams({csrf})}),
    f.identity,origin,f.ownerApi);
  assert.equal(success?.status,200);
  assert.equal(f.approved(),1);
});

test("first sign-in returns the browser to pending command-line approval",async()=>{
  const f=fixture();
  const redirect=await cliApproveResponse(new Request(url),f.identity,origin,f.ownerApi);
  assert.equal(redirect?.status,303);
  assert.equal(redirect?.headers.get("location"),"/sign-in");
  const ticket=redirect?.headers.get("set-cookie")?.split(";")[0];
  assert.match(ticket??"",/^__Host-kicad-cli-return=/);
  const afterLogin=await browserResponse(new Request(origin+"/account",{
    headers:{Cookie:"session=signed-in-owner; "+ticket}
  }),f.identity,origin);
  assert.equal(afterLogin?.status,303);
  assert.equal(afterLogin?.headers.get("location"),
    "/api/owner/cli/approve?request_id="+requestId);
  assert.match(afterLogin?.headers.get("set-cookie")??"",/Max-Age=0/);
  assert.equal(f.approved(),0,"returning to approval never implicitly approves");
});

test("owner CLI validation refuses malformed computer labels without opening the DB",async()=>{
  const pool={connect(){throw new Error("invalid label reached the database");}} as unknown as Pool;
  const ownerApi=new PgOwnerApiAccess(pool);
  for(const label of ["", "-computer", "A\\nB", "A<script>", "?stanbul", "A".repeat(65)]){
    assert.equal(await ownerApi.startRequest(requestId,label),false,label);
  }
});
