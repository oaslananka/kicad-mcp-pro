import assert from "node:assert/strict";
import {spawnSync} from "node:child_process";
import {readFileSync} from "node:fs";
import {dirname,join,resolve} from "node:path";
import {test} from "node:test";
import {fileURLToPath} from "node:url";

const cloud=resolve(dirname(fileURLToPath(import.meta.url)),"..");
const restore=readFileSync(join(cloud,"scripts/production-restore-drill.sh"),"utf8");
const start="ready=false\nfor _ in {1..35}; do";
const finish='[[ "$ready" == true ]] || { echo \'Isolated PostgreSQL unavailable\'; exit 1; }';

function readinessLoop():string {
  const begin=restore.indexOf(start);
  const end=restore.indexOf(finish,begin);
  assert.ok(begin>=0 && end>=begin,"operator readiness loop must be inspectable");
  return restore.slice(begin,end+finish.length);
}

// Simulate PostgreSQL's *first*, temporary bootstrap server reporting ready.
// A successful pg_isready is not sufficient until its final startup message.
function runMock(finalBoot:boolean,finalPgReady=true) {
  const script=String.raw`set -euo pipefail
target=synthetic
attempt=0
docker(){
  if [[ "$1" == logs ]]; then
    if [[ "$FINAL_BOOT" == yes ]] && ((attempt>=2)); then
      echo 'PostgreSQL init process complete; ready for start up'
    else
      echo 'database system is ready to accept connections'
    fi
    return 0
  fi
  if [[ "$1" == exec ]]; then
    if ((attempt<2)); then return 0; fi
    [[ "$FINAL_PG_READY" == yes ]]
    return
  fi
  return 7
}
sleep(){ attempt=$((attempt+1)); }
`+readinessLoop()+String.raw`
printf 'ATTEMPTS=%s\n' "$attempt"
`;
  return spawnSync("/bin/bash",["-c",script],{
    env:{...process.env,FINAL_BOOT:finalBoot?"yes":"no",FINAL_PG_READY:finalPgReady?"yes":"no"},
    encoding:"utf8",timeout:7000
  });
}

test("restore waits for final PostgreSQL boot, not a temporary pg_isready",{
  skip:process.platform==="win32"
},()=>{
  const run=runMock(true);
  assert.equal(run.status,0,run.stderr);
  assert.match(run.stdout,/ATTEMPTS=2/);
});

test("restore refuses when final startup log never appears, even if pg_isready passes",{
  skip:process.platform==="win32"
},()=>{
  const run=runMock(false);
  assert.notEqual(run.status,0,run.stdout);
  assert.match(run.stdout+run.stderr,/Isolated PostgreSQL unavailable/);
});

test("restore refuses when final PostgreSQL service is not available",{
  skip:process.platform==="win32"
},()=>{
  const run=runMock(true,false);
  assert.notEqual(run.status,0,run.stdout);
  assert.match(run.stdout+run.stderr,/Isolated PostgreSQL unavailable/);
});
