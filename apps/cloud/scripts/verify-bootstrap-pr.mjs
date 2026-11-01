#!/usr/bin/env node
// Independent new-host acceptance gate for a reviewed, unmerged PR.
// Input: three NUL-separated, public GitHub REST JSON responses (PR, checks, CI).
// Never passes Doppler credentials to GitHub and never modifies external state.
import {readFileSync} from "node:fs";

export function verifyAcceptance(pr,checks,runs,{number,head,base}) {
  const repository="oaslananka/kicad-mcp-pro-cloud";
  if(!Number.isSafeInteger(number)||number<1||!(/^[a-f0-9]{40}$/.test(head))||
     !(/^[a-f0-9]{40}$/.test(base)))return false;
  if(pr?.number!==number||pr?.state!=="open"||
     pr.head?.repo?.full_name!==repository||
     pr.base?.repo?.full_name!==repository||
     pr.base?.ref!=="main"||pr.base.sha!==base||pr.head.sha!==head)return false;
  // The exact PR SHA must have a successful real PR CI workflow, not
  // merely a green run from a different commit or from the main branch.
  if(!Array.isArray(runs?.workflow_runs)||
     !runs.workflow_runs.some(r=>r.head_sha===head&&r.event==="pull_request"&&
       r.status==="completed"&&r.conclusion==="success"))return false;
  if(!Array.isArray(checks?.check_runs))return false;
  const latest=new Map();
  for(const c of checks.check_runs) {
    if(typeof c?.name!=="string"||!Number.isSafeInteger(c.id))continue;
    const previous=latest.get(c.name);
    if(!previous||c.id>previous.id)latest.set(c.name,c);
  }
  // Reject pending, neutral, absent, failing, or superseded security gates.
  const required=[
    "check","SonarCloud Code Analysis","Codacy Static Code Analysis",
    "CodeQL","semgrep-cloud-platform/scan","GitGuardian Security Checks",
    "Socket Security: Pull Request Alerts","Analyze (javascript-typescript)",
    "Analyze (actions)"
  ];
  return required.every(name=>{
    const c=latest.get(name);
    return c?.status==="completed"&&c.conclusion==="success";
  });
}

if(process.argv[1]&&import.meta.url===new URL("file://"+process.argv[1]).href){
  let ok=false;
  try{
    const raw=readFileSync(0,"utf8").split("\0");
    if(raw.length===3){
      ok=verifyAcceptance(JSON.parse(raw[0]),JSON.parse(raw[1]),JSON.parse(raw[2]),{
        number:Number(process.argv[2]),head:process.argv[3],base:process.argv[4]
      });
    }
  }catch{}
  if(!ok){
    process.stderr.write("Exact-head pull request and completed security/CI proof unavailable; acceptance blocked\n");
    process.exitCode=1;
  }else{
    process.stdout.write("Verified exact PR head, reviewed base and successful security/CI gates\n");
  }
}
