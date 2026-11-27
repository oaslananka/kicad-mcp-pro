import assert from "node:assert/strict";
import {test} from "node:test";
import {randomBytes} from "node:crypto";
import {inIsolatedDatabase} from "./isolated-db.js";
import {cliApproveResponse,cliRequestId,ownerApiResponse,PgOwnerApiAccess} from "../src/owner-api.js";
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
  const ownerApi=new PgOwnerApiAccess(pool,"test-secret-only-for-fixtures");
  for(const label of ["", "-computer", "A\\nB", "A<script>", "?stanbul", "A".repeat(65)]){
    assert.equal(await ownerApi.startRequest(requestId,label,"test-source"),false,label);
  }
});


test("CLI token polling proves a secret distinct from the public browser identifier",async()=>{
  const secret="S".repeat(43);
  const publicId=cliRequestId(secret);
  assert.notEqual(secret,publicId);
  const calls:string[]=[];
  const ownerApi={
    startRequest:async(id:string,label:string,source:string)=>{
      assert.equal(id,publicId);
      assert.equal(label,"Fixture PC");
      assert.equal(source,"verified-source");
      return true;
    },
    getRequest:async(id:string)=>id===publicId?{state:"approved",label:"Fixture PC"}:null,
    issueToken:async(value:string)=>{
      calls.push(value);
      assert.equal(value,secret);
      return {token:"fixture-token",expiresAt:new Date("2026-12-01T00:00:00Z")};
    }
  } as unknown as PgOwnerApiAccess;
  const post=(path:string,body:object,source:string|null="verified-source")=>ownerApiResponse(
    new Request(origin+"/api/owner/cli/"+path,{method:"POST",
      headers:{"Content-Type":"application/json"},body:JSON.stringify(body)}),
    origin,{ownerApi,requestSource:source});
  const start={requestId:publicId,label:"Fixture PC",protocolVersion:2};
  assert.equal((await post("start",start,null))?.status,403);
  const accepted=await post("start",start);
  assert.equal(accepted?.status,200);
  const body=await accepted!.json() as {approveUrl:string};
  assert.equal(body.approveUrl,origin+"/api/owner/cli/approve?request_id="+publicId);
  assert.equal(body.approveUrl.includes(secret),false);
  assert.equal((await post("poll",{requestId:publicId}))?.status,426);
  assert.equal((await post("poll",{cliSecret:publicId,protocolVersion:2}))?.status,404);
  assert.deepEqual(calls,[]);
  const granted=await post("poll",{cliSecret:secret,protocolVersion:2});
  assert.equal(granted?.status,200);
  assert.deepEqual(calls,[secret]);
  assert.equal((await granted!.json() as {token:string}).token,"fixture-token");
});

test("owner CLI start quotas deny one source before inserting new requests",async()=>{
  let attempts=0,insertions=0;
  const pool={query:async(sql:string,params:unknown[])=>{
    if(sql.includes("pairing_device_budget")){
      assert.equal(typeof params[0],"string");
      assert.notEqual(params[0],"verified-source");
      return {rows:[{attempts:++attempts}]};
    }
    if(sql.includes("INSERT INTO owner_api_cli_requests")){
      insertions++;
      return {rowCount:1};
    }
    assert.fail("Unexpected query");
  }} as unknown as Pool;
  const api=new PgOwnerApiAccess(pool,"test-secret-only-for-fixtures");
  for(let i=0;i<12;i++)
    assert.equal(await api.startRequest(requestId,"Fixture PC","verified-source"),true);
  assert.equal(await api.startRequest(requestId,"Fixture PC","verified-source"),"throttled");
  assert.equal(insertions,12);
});

test("PostgreSQL owner approval expires and claims serialize without exposing the CLI secret",
  {skip:!process.env.TEST_DATABASE_URL},async()=>{
  await inIsolatedDatabase(process.env.TEST_DATABASE_URL!,[
    "012_pairing_device_budget.pgsql","022_usage_and_owner_api.pgsql"
  ],async db=>{
    const api=new PgOwnerApiAccess(db,"test-secret-only-for-fixtures");
    const secret=randomBytes(32).toString("base64url"),id=cliRequestId(secret);
    assert.equal(await api.startRequest(id,"Fixture PC","source-a"),true);
    assert.equal(await api.issueToken(secret),null);
    assert.equal(await api.approveRequest("owner",id),true);
    assert.equal(await api.issueToken(id),null);
    const claims=await Promise.all([api.issueToken(secret),api.issueToken(secret)]);
    assert.equal(claims.filter(Boolean).length,1);
    assert.equal(await api.verifyToken(claims.find(Boolean)!.token),"owner");
    assert.equal(await api.issueToken(secret),null);
    const oldSecret=randomBytes(32).toString("base64url"),oldId=cliRequestId(oldSecret);
    assert.equal(await api.startRequest(oldId,"Old PC","source-a"),true);
    assert.equal(await api.approveRequest("owner",oldId),true);
    await db.query("UPDATE owner_api_cli_requests SET updated_at=now()-interval '11 minutes' WHERE request_id=$1",[oldId]);
    assert.equal((await api.getRequest(oldId))?.state,"expired");
    assert.equal(await api.issueToken(oldSecret),null);
    const pending=cliRequestId(randomBytes(32).toString("base64url"));
    assert.equal(await api.startRequest(pending,"Pending PC","source-a"),true);
    await db.query("UPDATE owner_api_cli_requests SET created_at=now()-interval '11 minutes' WHERE request_id=$1",[pending]);
    assert.equal((await api.getRequest(pending))?.state,"expired");
    assert.equal(await api.approveRequest("owner",pending),false);
    const starts=await Promise.all(Array.from({length:16},()=>api.startRequest(
      cliRequestId(randomBytes(32).toString("base64url")),"Fixture PC","source-b")));
    assert.equal(starts.filter(v=>v===true).length,12);
    assert.equal(starts.filter(v=>v==="throttled").length,4);
    assert.equal(await api.startRequest(cliRequestId(randomBytes(32).toString("base64url")),
      "Another PC","source-c"),true);
  });
});
