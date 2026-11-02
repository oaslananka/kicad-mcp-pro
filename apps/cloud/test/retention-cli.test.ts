import assert from "node:assert/strict";
import {spawnSync} from "node:child_process";
import {test} from "node:test";

test("CLI rejects missing or ambiguous action and never defaults to destructive mode",()=>{
  const env={...process.env};
  delete env.DATABASE_URL;
  for(const args of [[],["--unknown"],["--apply","--dry-run"]]){
    const run=spawnSync(process.execPath,["--import","tsx","src/retention-cli.ts",...args],{
      env,encoding:"utf8",timeout:15_000
    });
    assert.equal(run.status,2);
    assert.match(run.stderr,/Usage/);
    assert.doesNotMatch(run.stderr,/postgresql:\/\//);
  }
  for(const args of [["--dry-run"],["--apply"]]){
    const run=spawnSync(process.execPath,["--import","tsx","src/retention-cli.ts",...args],{
      env,encoding:"utf8",timeout:15_000
    });
    assert.equal(run.status,2);
    assert.match(run.stderr,/DATABASE_URL/);
  }
});
