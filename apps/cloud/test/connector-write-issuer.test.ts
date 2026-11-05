import assert from "node:assert/strict";
import {createHash,generateKeyPairSync,verify} from "node:crypto";
import {chmod,link,mkdtemp,rm,symlink,writeFile} from "node:fs/promises";
import {tmpdir} from "node:os";
import path from "node:path";
import {test} from "node:test";
import {openPinnedOfflineWriteIssuer} from "../src/connector-write-issuer.js";

const now=1_800_000_000_000;
const deviceId="11111111-1111-4111-8111-111111111111";
const projectId="22222222-2222-4222-8222-222222222222";
const sessionId="33333333-3333-4333-8333-333333333333";
const binding={
  deviceId,projectId,sessionId,sessionExpiresUnixMs:now+20_000,
  allowedOperations:["pcb_move_footprint"]
};
function command(){
  return {
    kind:"connector.write_request",version:1,
    requestId:"44444444-4444-4444-8444-444444444444",
    deviceId,projectId,sessionId,deadlineUnixMs:now+1000,
    command:{
      operation:"pcb_move_footprint",reference:"R12",
      xMm:42.5,yMm:10.25,rotationDeg:null,expectedBoardSha256:"a".repeat(64)
    }
  };
}
function fixture(){
  const keys=generateKeyPairSync("ed25519");
  const pem=keys.privateKey.export({format:"pem",type:"pkcs8"});
  const publicDer=keys.publicKey.export({format:"der",type:"spki"}) as Buffer;
  const pin=createHash("sha256").update(publicDer).digest("hex");
  return {keys,pem,pin};
}

test("pinned offline write issuer rejects missing/invalid configuration",async()=>{
  await assert.rejects(openPinnedOfflineWriteIssuer("", ""),/OFFLINE_WRITE_ISSUER_CONFIG/);
  await assert.rejects(openPinnedOfflineWriteIssuer("relative.pem", "a".repeat(64)),
    /OFFLINE_WRITE_ISSUER_CONFIG/);
  await assert.rejects(openPinnedOfflineWriteIssuer("/not-present", "x".repeat(64)),
    /OFFLINE_WRITE_ISSUER_CONFIG/);
  await assert.rejects(openPinnedOfflineWriteIssuer("/not-present", "a".repeat(65)),
    /OFFLINE_WRITE_ISSUER_CONFIG/);
});

test("only pinned private owner-controlled Ed25519 material can issue a bounded proof",
  {skip:process.platform==="win32"},async()=>{
  const dir=await mkdtemp(path.join(tmpdir(),"cloud-write-issuer-"));
  try{
    const {keys,pem,pin}=fixture();
    const keyFile=path.join(dir,"issuer.pem");
    await writeFile(keyFile,pem,{mode:0o600});
    const sign=await openPinnedOfflineWriteIssuer(keyFile,pin);
    const raw=sign(command(),binding,now);
    assert.ok(raw);
    if(!raw)return;
    const envelope=JSON.parse(raw.toString("utf8")) as {
      payload:string;signature:string;kind:string;version:number;
    };
    assert.equal(envelope.kind,"connector.signed_write_proposal");
    assert.equal(envelope.version,1);
    const payload=Buffer.from(envelope.payload,"base64url");
    const signature=Buffer.from(envelope.signature,"base64url");
    assert.equal(verify(null,Buffer.concat([
      Buffer.from("kicad-cloud-signed-write-proposal-v1\0"),payload
    ]),keys.publicKey,signature),true);
    assert.equal(sign({...command(),shell:"unauthorized"},binding,now),null);
    assert.equal(sign(command(),{...binding,allowedOperations:[]},now),null);
    assert.equal(sign(command(),binding,now+1001),null);
    await assert.rejects(openPinnedOfflineWriteIssuer(keyFile,"0".repeat(64)),
      /OFFLINE_WRITE_ISSUER_UNTRUSTED/);
    await chmod(keyFile,0o644);
    await assert.rejects(openPinnedOfflineWriteIssuer(keyFile,pin),
      /OFFLINE_WRITE_ISSUER_UNTRUSTED/);
    await chmod(keyFile,0o600);
    const alias=path.join(dir,"hardlink.pem");
    await link(keyFile,alias);
    await assert.rejects(openPinnedOfflineWriteIssuer(keyFile,pin),
      /OFFLINE_WRITE_ISSUER_UNTRUSTED/);
    await rm(alias);
    const shortcut=path.join(dir,"symlink.pem");
    await symlink(keyFile,shortcut);
    await assert.rejects(openPinnedOfflineWriteIssuer(shortcut,pin),
      /OFFLINE_WRITE_ISSUER_UNTRUSTED/);
  }finally{
    await rm(dir,{recursive:true,force:true});
  }
});

test("non-Ed25519 signing material and public-only keys are refused",
  {skip:process.platform==="win32"},async()=>{
  const dir=await mkdtemp(path.join(tmpdir(),"cloud-write-issuer-negative-"));
  try{
    const good=fixture();
    const filename=path.join(dir,"issuer.pem");
    const rsa=generateKeyPairSync("rsa",{modulusLength:2048});
    const rsaPem=rsa.privateKey.export({format:"pem",type:"pkcs8"});
    await writeFile(filename,rsaPem,{mode:0o600});
    await assert.rejects(openPinnedOfflineWriteIssuer(filename,good.pin),
      /OFFLINE_WRITE_ISSUER_UNTRUSTED/);
    const publicOnly=good.keys.publicKey.export({format:"pem",type:"spki"});
    await writeFile(filename,publicOnly,{mode:0o600});
    await assert.rejects(openPinnedOfflineWriteIssuer(filename,good.pin),
      /OFFLINE_WRITE_ISSUER_UNTRUSTED/);
  }finally{
    await rm(dir,{recursive:true,force:true});
  }
});
