import test from "node:test";
import assert from "node:assert/strict";
import {generateKeyPairSync,verify,createHash} from "node:crypto";
import {createSignedGenericMcpProposal} from "../src/connector-generic-mcp-proof.js";

const keys=generateKeyPairSync("ed25519");
const deviceId="11111111-1111-4111-8111-111111111111";
const projectId="22222222-2222-4222-8222-222222222222";
const sessionId="33333333-3333-4333-8333-333333333333";
const requestId="44444444-4444-4444-8444-444444444444";
const now=3000000000000;

const binding={
  deviceId,projectId,sessionId,sessionExpiresUnixMs:now+20_000,
  allowedOperations:["mcp_bridge"]
};

test("generic tool proof binds exact args, tool, owner project and signed session",()=>{
  const argumentsJson=JSON.stringify({reference:"R2"});
  const candidate={kind:"connector.mcp_tool_write",version:1,requestId,
    deviceId,projectId,sessionId,deadlineUnixMs:now+5000,
    toolName:"sch_add_symbol",argumentsJson};
  const signed=createSignedGenericMcpProposal(candidate,binding,now,keys.privateKey);
  assert.ok(signed);
  const proposal=JSON.parse(signed!.toString("utf8"));
  assert.equal(proposal.kind,"connector.signed_mcp_tool");
  const payload=Buffer.from(proposal.payload,"base64url");
  const parsed=JSON.parse(payload.toString("utf8"));
  assert.equal(parsed.argumentsSha256,createHash("sha256").update(argumentsJson).digest("hex"));
  assert.equal(parsed.argumentsJson,undefined);
  assert.equal(verify(null,Buffer.concat([
    Buffer.from("kicad-cloud-signed-mcp-tool-v1\0","utf8"),payload
  ]),keys.publicKey,Buffer.from(proposal.signature,"base64url")),true);
  assert.equal(createSignedGenericMcpProposal({...candidate,sessionId:"55555555-5555-4555-8555-555555555555"},binding,now,keys.privateKey),null);
  assert.equal(createSignedGenericMcpProposal({...candidate,toolName:"export_manufacturing_package"},binding,now,keys.privateKey),null);
  assert.equal(createSignedGenericMcpProposal({...candidate,deadlineUnixMs:now+12_000},binding,now,keys.privateKey),null);
  assert.equal(createSignedGenericMcpProposal(candidate,{...binding,allowedOperations:[]},now,keys.privateKey),null);
});
