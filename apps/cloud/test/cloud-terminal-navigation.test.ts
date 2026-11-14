import assert from "node:assert/strict";
import {test} from "node:test";
import {renderPage} from "../src/ui-shell.js";

test("Cloud sidebar remains stable across pages even when identity metadata varies",()=>{
  for(const kind of ["devices","projects","connections","usage","account","settings"] as const){
    const a=renderPage({title:"Current",kind,children:null,userEmail:"person@example.test"});
    const b=renderPage({title:"Current",kind,children:null});
    const nav=(s:string)=>s.match(/<aside class="workspace-sidebar"[\s\S]*?<\/aside>/)?.[0];
    assert.ok(nav(a));
    assert.equal(nav(a),nav(b));
    assert.match(a,/href="\/devices"/);
    assert.match(a,/href="\/account" class="sidebar-profile"/);
    assert.match(a,/class="profile-identity">Account<\/span>/);
    assert.match(a,/Activity<\/a>/);
    assert.doesNotMatch(nav(a)!,/person@example\.test/);
    assert.doesNotMatch(nav(a)!,/href="\/projects"/);
  }
});


test("Cloud account and Activity show measured totals, never inferred values",async()=>{
  const {renderAccount}=await import("../src/browser-ui.js");
  const {renderUsagePage}=await import("../src/usage-ui.js");
  const account=renderAccount("Tester",["github"],[],{devices:1,projects:0,clients:1,grants:0},
    "tester@example.test",false,1234);
  assert.match(account,/Cloud tool calls/);
  assert.match(account,/1[.,]234/);
  assert.match(account,/href="\/usage"/);
  const empty=renderUsagePage(null,undefined,0);
  assert.match(empty,/0 Cloud tool calls recorded/);
  assert.match(empty,/All recorded Cloud MCP calls/);
  const unavailable=renderUsagePage();
  assert.match(unavailable,/Cloud telemetry is unavailable/);
  assert.doesNotMatch(unavailable,/0 Cloud tool calls recorded/);
});
