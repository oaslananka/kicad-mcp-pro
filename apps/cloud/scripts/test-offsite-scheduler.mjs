import assert from "node:assert/strict";
import {spawnSync} from "node:child_process";
import {createHash} from "node:crypto";
import {mkdtempSync,mkdirSync,copyFileSync,writeFileSync,readFileSync,existsSync,rmSync,chmodSync} from "node:fs";
import {tmpdir} from "node:os";
import {dirname,join,resolve} from "node:path";
import test from "node:test";
import {fileURLToPath} from "node:url";

const source=resolve(dirname(fileURLToPath(import.meta.url)), "..");
const install=readFileSync(join(source,"scripts/install-offsite-backup-timer.sh"),"utf8");
const push=readFileSync(join(source,"scripts/offsite-backup-push.sh"),"utf8");
const restore=join(source,"scripts/offsite-restore-verify.sh");

function fixture() {
  const root=mkdtempSync(join(tmpdir(),"cloud-offsite-contract-"));
  const repo=join(root,"checkout");
  const home=join(root,"home");
  const bin=join(root,"bin");
  mkdirSync(join(repo,"scripts"),{recursive:true});
  mkdirSync(home,{recursive:true});
  mkdirSync(bin,{recursive:true});
  for(const name of ["install-offsite-backup-timer.sh","doppler-runtime.sh"]) {
    copyFileSync(join(source,"scripts",name),join(repo,"scripts",name));
  }
  const mocks={
    git:"#!/usr/bin/env bash\n[[ \"${FIXTURE_DIRTY:-}\" != yes ]] || echo ' M pending-file'\n",
    doppler:`#!/usr/bin/env bash
set -euo pipefail
[[ "$1" == run ]] || exit 10
while [[ "$1" != -- ]]; do [[ $# -gt 0 ]] || exit 11; shift; done
shift
exec env OFFSITE_REMOTE_SSH="\${FIXTURE_REMOTE_SSH:-}" OFFSITE_REMOTE_DIR="\${FIXTURE_REMOTE_DIR:-}" KICAD_BACKUP_AGE_IDENTITY="\${FIXTURE_AGE_IDENTITY:-}" KICAD_BACKUP_AGE_RECIPIENT="\${FIXTURE_AGE_RECIPIENT:-}" "$@"
`,
    systemctl:String.raw`#!/usr/bin/env bash
printf '%s\n' "$*" >> "$HOME/systemctl.log"
`
  };
  for(const [name,content] of Object.entries(mocks)){
    const f=join(bin,name);
    writeFileSync(f,content,{mode:0o700});
  }
  const env={
    ...process.env,HOME:home,PATH:bin+":"+process.env.PATH,
    FIXTURE_AGE_IDENTITY:"synthetic-test-identity",
    FIXTURE_AGE_RECIPIENT:"synthetic-test-recipient",
    FIXTURE_REMOTE_SSH:"backup@127.0.0.1",
    FIXTURE_REMOTE_DIR:"/private/kicad/offsite"
  };
  return {root,repo,home,env,run:(patch={})=>spawnSync("/usr/bin/bash",[join(repo,"scripts/install-offsite-backup-timer.sh")],{env:{...env,...patch},encoding:"utf8",timeout:10000})};
}

test("Doppler-only timer preflight rejects missing/invalid destination without touching systemd",()=>{
  const f=fixture();
  try {
    for(const patch of [
      {FIXTURE_REMOTE_SSH:""},
      {FIXTURE_REMOTE_DIR:""},
      {FIXTURE_REMOTE_SSH:"backup@not-an-ip"},
      {FIXTURE_REMOTE_DIR:"/private/../sensitive"},
      {FIXTURE_AGE_IDENTITY:""}
    ]) {
      const result=f.run(patch);
      assert.notEqual(result.status,0,JSON.stringify(patch));
      assert.match(result.stderr,/Doppler offsite destination or age configuration/);
      assert.equal(existsSync(join(f.home,".config/systemd/user/kicad-cloud-offsite.timer")),false);
      assert.equal(existsSync(join(f.home,"systemctl.log")),false);
    }
    const dirty=f.run({FIXTURE_DIRTY:"yes"});
    assert.notEqual(dirty.status,0);
    assert.match(dirty.stderr,/Release worktree must be clean/);
    assert.equal(existsSync(join(f.home,"systemctl.log")),false);
  } finally {rmSync(f.root,{recursive:true,force:true});}
});

test("valid synthetic Doppler values create only the expected timer and wrapped service",()=>{
  const f=fixture();
  try{
    const result=f.run();
    assert.equal(result.status,0,result.stderr);
    const dir=join(f.home,".config/systemd/user");
    const unit=readFileSync(join(dir,"kicad-cloud-offsite.service"),"utf8");
    const timer=readFileSync(join(dir,"kicad-cloud-offsite.timer"),"utf8");
    assert.match(unit,/ExecStart=\/usr\/bin\/bash .*\/scripts\/doppler-runtime\.sh \/usr\/bin\/bash .*\/scripts\/offsite-backup-push\.sh/);
    assert.doesNotMatch(unit,/EnvironmentFile/);
    assert.doesNotMatch(unit,/127\.0\.0\.1|synthetic-test|OFFSITE_REMOTE_DIR=/);
    assert.match(timer,/OnCalendar=daily/);
    assert.match(readFileSync(join(f.home,"systemctl.log"),"utf8"),/enable --now kicad-cloud-offsite\.timer/);
  }finally{rmSync(f.root,{recursive:true,force:true});}
});

test("source and independent restore accept 13 and reject mismatched versioned migration receipts",()=>{
  const regexLine=push.split("\n").find(x=>x.includes('"${ledger%%:*}" == "$version"'));
  assert.ok(regexLine,"actual source migration guard");
  for(const [version,count,pass] of [
    ["12","12",true],["13","13",true],["14","13",false],["0","0",false],["1000","1000",false]
  ]){
    const ledger=count+":"+"a".repeat(32);
    const result=spawnSync("/usr/bin/bash",["-c",`version="$1"; ledger="$2"; ${regexLine}`,"fixture",version,ledger],{encoding:"utf8"});
    assert.equal(result.status===0,pass,version+"/"+count);
  }
  const dir=mkdtempSync(join(tmpdir(),"cloud-offsite-archive-"));
  try{
    const file=join(dir,"ciphertext.pg.age");
    writeFileSync(file,"synthetic-only-no-real-backup",{mode:0o600});
    chmodSync(file,0o600);
    const sha=createHash("sha256").update(readFileSync(file)).digest("hex");
    const env={...process.env,EXPECTED_SHA256:sha,EXPECTED_LEDGER:"13:"+"a".repeat(32)};
    const valid=spawnSync("/usr/bin/bash",[restore,file],{env:{...env,EXPECTED_SCHEMA_VERSION:"13",KICAD_BACKUP_AGE_IDENTITY:"",KICAD_BACKUP_AGE_RECIPIENT:""},encoding:"utf8"});
    assert.equal(valid.status,2);
    assert.match(valid.stderr,/Independent operator must provide authorized age identity/);
    const invalid=spawnSync("/usr/bin/bash",[restore,file],{env:{...env,EXPECTED_SCHEMA_VERSION:"14"},encoding:"utf8"});
    assert.equal(invalid.status,2);
    assert.match(invalid.stderr,/checksum receipt\/count must match schema version/);
  }finally{rmSync(dir,{recursive:true,force:true});}
});
