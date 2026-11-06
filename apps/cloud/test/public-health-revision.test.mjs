import test from "node:test";
import assert from "node:assert/strict";
import {readPublicHealthRevision} from "../scripts/read-public-health-revision.mjs";

const REVISION="a".repeat(40);
const ORIGIN="https://pcb.example.test/";

test("reads only public JSON metadata from an exact HTTPS health endpoint",async()=>{
  const requests=[];
  const actual=await readPublicHealthRevision(ORIGIN,{requireOk:true,
    fetchImpl:async (url,options)=>{
      requests.push({href:url.href,redirect:options.redirect,accept:options.headers.Accept});
      return {ok:true,json:async()=>({status:"ok",revision:REVISION})};
    }});
  assert.equal(actual,REVISION);
  assert.deepEqual(requests,[{href:"https://pcb.example.test/health",redirect:"error",accept:"application/json"}]);
});

test("never fetches untrusted origins or URLs with credentials and query",async()=>{
  for(const origin of ["http://pcb.example.test","https://user:password@pcb.example.test/",
      "https://pcb.example.test/?token=bad","https://pcb.example.test/admin/"]){
    await assert.rejects(readPublicHealthRevision(origin,{fetchImpl:()=>{throw Error("unsafe request");}}));
  }
});

test("fails closed for HTTP, JSON and unhealthy status without executing remote content",async()=>{
  await assert.rejects(readPublicHealthRevision(ORIGIN,{
    fetchImpl:async()=>({ok:false,json:async()=>({status:"ok",revision:REVISION})})}));
  for(const payload of [null,{}, {status:"error",revision:REVISION},
      {status:"ok",revision:"unknown"}, {status:"ok",revision:"<script>alert(1)</script>"}]){
    await assert.rejects(readPublicHealthRevision(ORIGIN,{requireOk:true,
      fetchImpl:async()=>({ok:true,json:async()=>payload})}));
  }
});

test("read mode permits a valid revision even before full readiness",async()=>{
  assert.equal(await readPublicHealthRevision(ORIGIN,{fetchImpl:async()=>
    ({ok:true,json:async()=>({status:"starting",revision:REVISION})})}),REVISION);
});
