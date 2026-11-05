import assert from "node:assert/strict";
import {generateKeyPairSync,verify} from "node:crypto";
import {test} from "node:test";
import {
  createOfflineSignedWriteProposal,MAX_SIGNED_WRITE_PROPOSAL_BYTES
} from "../src/connector-write-proof.js";

const now=1_800_000_000_000;
const deviceId="11111111-1111-4111-8111-111111111111";
const projectId="22222222-2222-4222-8222-222222222222";
const sessionId="33333333-3333-4333-8333-333333333333";
const requestId="44444444-4444-4444-8444-444444444444";
const binding={
  deviceId,projectId,sessionId,sessionExpiresUnixMs:now+20_000,
  allowedOperations:["pcb_move_footprint"]
};
const keyPair=generateKeyPairSync("ed25519");

function command(){
  return {
    kind:"connector.write_request",version:1,requestId,deviceId,projectId,sessionId,
    deadlineUnixMs:now+1000,
    command:{
      operation:"pcb_move_footprint",reference:"R12",xMm:42.5,yMm:10.25,
      rotationDeg:null,expectedBoardSha256:"a".repeat(64)
    }
  };
}
function issue(raw:unknown=command(),scope=binding,at=now){
  return createOfflineSignedWriteProposal(raw,scope,at,keyPair.privateKey);
}

test("offline Cloud proof matches the local Ed25519 wire envelope",()=>{
  const raw=issue();
  assert.ok(raw);
  if(!raw)return;
  assert.ok(raw.length<=MAX_SIGNED_WRITE_PROPOSAL_BYTES);
  const envelope=JSON.parse(raw.toString("utf8")) as Record<string,unknown>;
  assert.deepEqual(Object.keys(envelope).sort(),["kind","payload","signature","version"]);
  assert.equal(envelope.kind,"connector.signed_write_proposal");
  assert.equal(envelope.version,1);
  const payload=Buffer.from(String(envelope.payload),"base64url");
  const signature=Buffer.from(String(envelope.signature),"base64url");
  assert.equal(payload.toString("base64url"),envelope.payload);
  assert.equal(signature.toString("base64url"),envelope.signature);
  assert.deepEqual(JSON.parse(payload.toString("utf8")),command());
  assert.equal(signature.length,64);
  const signed=Buffer.concat([Buffer.from("kicad-cloud-signed-write-proposal-v1\0"),payload]);
  assert.ok(verify(null,signed,keyPair.publicKey,signature));
  const other=generateKeyPairSync("ed25519");
  assert.equal(verify(null,signed,other.publicKey,signature),false);
  assert.equal(verify(null,Buffer.concat([signed,Buffer.from("changed")]),
    keyPair.publicKey,signature),false);
});

test("invalid owner, project, session, grant or deadline cannot produce proof",()=>{
  assert.equal(issue(command(),{...binding,deviceId:projectId}),null);
  assert.equal(issue(command(),{...binding,projectId:deviceId}),null);
  assert.equal(issue(command(),{...binding,sessionId:projectId}),null);
  assert.equal(issue(command(),{...binding,allowedOperations:[]}),null);
  assert.equal(issue(command(),{...binding,sessionExpiresUnixMs:now+500}),null);
  assert.equal(issue(command(),binding,now+1000),null);
  assert.equal(issue(command(),binding,Number.NaN),null);
});

test("strict write allowlist denies arbitrary operations, paths and malformed values",()=>{
  const original=command();
  assert.equal(issue({...original,shell:"rm -rf ."}),null);
  assert.equal(issue({...original,command:{...original.command,path:"/etc/passwd"}}),null);
  assert.equal(issue({...original,command:{...original.command,operation:"pcb_delete_all"}}),null);
  assert.equal(issue({...original,command:{...original.command,reference:"../../board"}}),null);
  assert.equal(issue({...original,command:{...original.command,xMm:1001}}),null);
  assert.equal(issue({...original,command:{...original.command,rotationDeg:Number.NaN}}),null);
  assert.equal(issue({...original,requestId:"not-a-uuid"}),null);
  assert.equal(issue({...original,deadlineUnixMs:now+10_001}),null);
  assert.equal(issue({...original,kind:"connector.read_request"}),null);
  assert.equal(issue(JSON.stringify(original)),null,"raw JSON needs duplicate-key rejection");
  assert.equal(issue(null),null);
});

test("issuer refuses non-Ed25519 or public-only keys",()=>{
  const rsa=generateKeyPairSync("rsa",{modulusLength:2048});
  assert.equal(createOfflineSignedWriteProposal(command(),binding,now,keyPair.publicKey),null);
  assert.equal(createOfflineSignedWriteProposal(command(),binding,now,rsa.privateKey),null);
  assert.equal(createOfflineSignedWriteProposal(command(),binding,now,null as never),null);
  assert.equal(createOfflineSignedWriteProposal(command(),binding,now,{} as never),null);
});

test("issuer does not add file paths, credentials or authorization claims",()=>{
  const raw=issue();
  assert.ok(raw);
  assert.equal(raw.includes(Buffer.from("privateKey")),false);
  assert.equal(raw.includes(Buffer.from("localPath")),false);
  assert.equal(raw.includes(Buffer.from("clientSecret")),false);
  const candidate=command();
  assert.equal(issue(candidate)?.toString("utf8"),raw.toString("utf8"),
    "proof generation is deterministic; one-use storage is a separate required gate");
  assert.deepEqual(candidate,command(),"input must not be mutated");
});
