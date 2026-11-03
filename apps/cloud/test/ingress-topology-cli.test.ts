import assert from "node:assert/strict";
import {spawnSync} from "node:child_process";
import {test} from "node:test";

test("operator CLI never guesses names, networks or trust address",()=>{
  for(const params of [
    [],["--app","a"],["--app","a","--proxy","b","--network","private"],
    ["--app","a","--app","a","--network","n","--expected-peer","127.0.0.1"],
    ["--app","a;rm -rf /","--proxy","b","--network","n","--expected-peer","127.0.0.1"]
  ]){
    const r=spawnSync(process.execPath,[
      "--import","tsx","src/ingress-topology-cli.ts",...params
    ],{encoding:"utf8",timeout:15_000});
    assert.equal(r.status,2,r.stderr);
    assert.match(r.stderr,/Usage:/);
  }
});
