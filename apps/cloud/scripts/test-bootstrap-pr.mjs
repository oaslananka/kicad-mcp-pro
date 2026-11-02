import test from "node:test";
import assert from "node:assert/strict";
import {verifyAcceptance} from "./verify-bootstrap-pr.mjs";

const head="b189aeaadef23f226e6438d00655922484c46143";
const base="1697bf37f689aac3f16eca2dc0b5827f055e9795";
const repository={full_name:"oaslananka/kicad-mcp-pro"};
const required=[
  "check","SonarCloud Code Analysis","Codacy Static Code Analysis",
  "CodeQL","semgrep-cloud-platform/scan","GitGuardian Security Checks",
  "Socket Security: Pull Request Alerts","Analyze (javascript-typescript)",
  "Analyze (actions)"
];
function fixture(){
  return {
    pr:{number:63,state:"open",head:{sha:head,repo:repository},
      base:{sha:base,ref:"main",repo:repository}},
    checks:{check_runs:required.map((name,i)=>({
      id:i+1,name,status:"completed",conclusion:"success"
    }))},
    runs:{workflow_runs:[{head_sha:head,event:"pull_request",
      status:"completed",conclusion:"success"}]},
    params:{number:63,head,base}
  };
}
function verified(f){return verifyAcceptance(f.pr,f.checks,f.runs,f.params);}
test("exact reviewed same-repo PR with all security and CI gates succeeds",()=>{
  assert.equal(verified(fixture()),true);
});
test("reject missing, pending, neutral and failing security gates",()=>{
  for(const name of required){
    for(const state of ["missing","pending","neutral","failure"]){
      const f=fixture();
      f.checks.check_runs=f.checks.check_runs.filter(c=>c.name!==name);
      if(state!=="missing")f.checks.check_runs.push({
        id:300,name,status:state==="pending"?"in_progress":"completed",
        conclusion:state==="pending"?null:state
      });
      assert.equal(verified(f),false,name+" "+state);
    }
  }
});
test("newer failed check overrides an older success for same name",()=>{
  const f=fixture();
  f.checks.check_runs.push({
    id:100,name:"check",status:"completed",conclusion:"failure"
  });
  assert.equal(verified(f),false);
});
test("reject fork, changed base, stale checkout, closed PR or wrong number",()=>{
  for(const action of [
    f=>f.pr.head.repo.full_name="somebody/fork",
    f=>f.pr.base.repo.full_name="somebody/fork",
    f=>f.pr.base.ref="develop",
    f=>f.pr.base.sha="f".repeat(40),
    f=>f.pr.head.sha="f".repeat(40),
    f=>f.pr.state="closed",
    f=>f.pr.number=64,
    f=>f.params.head="0".repeat(40),
    f=>f.params.number=64
  ]){
    const f=fixture();action(f);
    assert.equal(verified(f),false);
  }
});
test("reject wrong run origin, pending CI, stale CI, or absent CI",()=>{
  for(const action of [
    f=>f.runs.workflow_runs[0].head_sha="f".repeat(40),
    f=>f.runs.workflow_runs[0].event="push",
    f=>f.runs.workflow_runs[0].status="in_progress",
    f=>f.runs.workflow_runs[0].conclusion="failure",
    f=>f.runs.workflow_runs=[]
  ]){
    const f=fixture();action(f);
    assert.equal(verified(f),false);
  }
});
