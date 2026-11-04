import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {test} from "node:test";
import {parseUntrustedWriteRequest,MAX_WRITE_FRAME_BYTES} from "../src/connector-write-contract.js";

const deviceId="11111111-1111-4111-8111-111111111111";
const projectId="22222222-2222-4222-8222-222222222222";
const sessionId="33333333-3333-4333-8333-333333333333";
const now=1_800_000_000_000;
const binding={deviceId,projectId,sessionId,sessionExpiresUnixMs:now+20_000,
  allowedOperations:["pcb_move_footprint"]};
function fixture(){return {
  kind:"connector.write_request",version:1,
  requestId:"44444444-4444-4444-8444-444444444444",
  deviceId,projectId,sessionId,deadlineUnixMs:now+1000,
  command:{operation:"pcb_move_footprint",reference:"R12",xMm:42.5,
    yMm:10.25,rotationDeg:null,expectedBoardSha256:"a".repeat(64)}
};}

test("strict offline command envelope accepts only a bounded footprint move",()=>{
  const valid=fixture();
  assert.deepEqual(parseUntrustedWriteRequest(valid,binding,now),valid);
  assert.equal(parseUntrustedWriteRequest(JSON.stringify(valid),binding,now),null,
    "raw wire JSON must be parsed by a duplicate-key-rejecting transport");
  for(const malicious of [
    {...valid,operation:"run_shell"},{...valid,cmd:"rm -rf /"},
    {...valid,projectId:deviceId},{...valid,deviceId:projectId},
    {...valid,sessionId:projectId},
    {...valid,deadlineUnixMs:now},{...valid,deadlineUnixMs:now+10001},
    {...valid,deadlineUnixMs:NaN},{...valid,requestId:"not-a-uuid"},
    {...valid,version:2},{...valid,kind:"connector.read_request"},
    {...valid,command:{...valid.command,operation:"pcb_delete_all"}},
    {...valid,command:{...valid.command,reference:"../../board"}},
    {...valid,command:{...valid.command,reference:"<script>"}},
    {...valid,command:{...valid.command,xMm:1001}},
    {...valid,command:{...valid.command,yMm:Number.POSITIVE_INFINITY}},
    {...valid,command:{...valid.command,rotationDeg:361}},
    {...valid,command:{...valid.command,expectedBoardSha256:"A".repeat(64)}},
    {...valid,command:{...valid.command,localPath:"/etc/passwd"}}
  ])assert.equal(parseUntrustedWriteRequest(malicious,binding,now),null);
  assert.equal(parseUntrustedWriteRequest(JSON.stringify(valid).padEnd(MAX_WRITE_FRAME_BYTES+1," "),binding,now),null);
  assert.equal(parseUntrustedWriteRequest(valid,{...binding,sessionId:projectId},now),null);
  assert.equal(parseUntrustedWriteRequest(valid,{...binding,allowedOperations:[]},now),null);
  assert.equal(parseUntrustedWriteRequest(valid,{...binding,sessionExpiresUnixMs:now+500},now),null);
  assert.equal(parseUntrustedWriteRequest(valid,{...binding,sessionExpiresUnixMs:now},now),null);
  assert.equal(parseUntrustedWriteRequest(valid,binding,NaN),null);
  assert.equal(parseUntrustedWriteRequest("{bad json",binding,now),null);
});

test("v1 write contract matches the shared Python/TypeScript golden fixture",()=>{
  const fixtureFile=readFileSync(
    new URL("../../../tests/fixtures/cloud_write_contract_v1.json",import.meta.url),"utf8");
  const golden=JSON.parse(fixtureFile) as unknown;
  assert.deepEqual(parseUntrustedWriteRequest(golden,binding,now),fixture());
});
