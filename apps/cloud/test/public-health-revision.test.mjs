import test from "node:test";
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {readPublicHealthRevision} from "../scripts/read-public-health-revision.mjs";
import {assertLandingStructuredData} from "../scripts/production-page-check.mjs";

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

test("Cloud production container allows only its two required build helpers",()=>{
  const dockerfile=readFileSync(new URL("../Dockerfile",import.meta.url),"utf8")
    .replace(/\r\n/g,"\n");
  const ignore=readFileSync(new URL("../.dockerignore",import.meta.url),"utf8")
    .replace(/\r\n/g,"\n");
  const expected=[
    "scripts/copy-client-assets.mjs",
    "scripts/build-project-review.mjs"
  ];
  const copyLines=dockerfile.split("\n").filter(line=>/^COPY scripts\//.test(line));
  assert.deepEqual(copyLines,[
    "COPY scripts/copy-client-assets.mjs scripts/build-project-review.mjs ./scripts/"
  ]);
  assert.ok(dockerfile.indexOf(copyLines[0]) <
    dockerfile.indexOf("RUN npm run build"),"build helpers must be copied before npm build");
  assert.match(dockerfile,/^COPY src \.\/src$/m);
  assert.match(ignore,/^scripts\/\*$/m);
  const exceptions=ignore.split("\n").filter(line=>line.startsWith("!scripts/"));
  assert.deepEqual(exceptions,expected.map(path=>"!"+path));
  assert.doesNotMatch(dockerfile,/COPY scripts\s+\.\/scripts/);
});
test("landing smoke permits inert canonical JSON-LD and rejects executable or unexpected scripts",()=>{
  const origin="https://pcb.example.test";
  const data={"@context":"https://schema.org","@type":"SoftwareApplication",url:origin+"/"};
  const valid='<script type="application/ld+json">'+JSON.stringify(data)+"</script>";
  assert.doesNotThrow(()=>assertLandingStructuredData(valid,origin));
  for(const page of ["",valid+'<script src="/unexpected.js"></script>',
      '<script type="text/javascript">alert(1)</script>',
      valid.replace('type="application/ld+json"','type="application/ld+json" onload="bad()"'),
      valid.replace(origin,"https://foreign.example.test"),
      valid.replace(JSON.stringify(data),"not-json")]){
    assert.throws(()=>assertLandingStructuredData(page,origin));
  }
});
