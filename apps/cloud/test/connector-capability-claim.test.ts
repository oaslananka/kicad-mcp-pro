import assert from "node:assert/strict";
import {test} from "node:test";
import {parseCapabilityClaim, allowsClaimedRead} from "../src/connector-capability-claim.js";

const revision="a".repeat(64);
const valid={
  schemaVersion:"1.0.0",catalogRevision:revision,
  operations:["project_summary","project_board_counts"]
};

test("legacy clients without a catalog claim remain compatible",()=>{
  assert.equal(parseCapabilityClaim(undefined),null);
  assert.equal(allowsClaimedRead(null,"project_summary"),true);
  assert.equal(allowsClaimedRead(null,"run_drc"),true);
});

test("valid bounded claims only narrow operations; they do not grant permission",()=>{
  const claim=parseCapabilityClaim(valid);
  assert.ok(claim);
  assert.equal(claim.catalogRevision,revision);
  assert.equal(allowsClaimedRead(claim,"project_summary"),true);
  assert.equal(allowsClaimedRead(claim,"run_drc"),false);
  assert.equal(allowsClaimedRead(parseCapabilityClaim({...valid,operations:[]}),"project_summary"),false);
});

test("malformed, outdated and unsafe claims fail closed",()=>{
  for(const malformed of [
    null,{...valid,schemaVersion:"2.0.0"},
    {...valid,catalogRevision:"../private"},
    {...valid,catalogRevision:"ABCDEF".repeat(10)+"ABCD"},
    {...valid,operations:["project_summary","project_summary"]},
    {...valid,operations:["shell.execute"]},
    {...valid,operations:["run_erc"]},
    {...valid,operations:["project_summary"],localPath:"/secret"},
    {...valid,operations:Array(6).fill("project_summary")},
    {...valid,operations:"project_summary"}
  ]){
    assert.equal(parseCapabilityClaim(malformed),null,JSON.stringify(malformed));
  }
});
