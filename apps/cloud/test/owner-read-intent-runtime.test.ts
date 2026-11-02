import assert from "node:assert/strict";
import {generateKeyPairSync,randomUUID} from "node:crypto";
import {mkdtemp,writeFile,chmod,link,symlink,rm} from "node:fs/promises";
import {tmpdir} from "node:os";
import path from "node:path";
import test from "node:test";
import {openConfiguredOwnerIntentDelivery} from "../src/owner-read-intent-runtime.js";

const CLOUD="https://cloud.example.test";
const AUTHORITY="https://owner.example.test";
const ready={wsEnabled:true,ownerConsentEnabled:true,identityEnabled:true};

const enabled=(keyPath:string)=>({
  OWNER_READ_INTENT_DELIVERY_ENABLED:"true",
  OWNER_READ_INTENT_DELIVERY_ORIGIN:AUTHORITY,
  OWNER_READ_INTENT_DELIVERY_SIGNING_KEY_FILE:keyPath
});

test("owner-intent runtime has no implicit live delivery",async()=>{
  assert.equal(await openConfiguredOwnerIntentDelivery({},CLOUD,ready),null);
  assert.equal(await openConfiguredOwnerIntentDelivery({
    OWNER_READ_INTENT_DELIVERY_ENABLED:"false"
  },CLOUD,ready),null);
  await assert.rejects(openConfiguredOwnerIntentDelivery({
    OWNER_READ_INTENT_DELIVERY_ENABLED:"yes"
  },CLOUD,ready),/Invalid owner-intent delivery/);
});

test("opt-in fails before private-key access unless trusted services are enabled",async()=>{
  for(const field of ["wsEnabled","ownerConsentEnabled","identityEnabled"] as const){
    await assert.rejects(openConfiguredOwnerIntentDelivery(enabled("/missing/key"),CLOUD,{
      ...ready,[field]:false
    }),/requires identity, WSS and independent receipt consumer/);
  }
  await assert.rejects(openConfiguredOwnerIntentDelivery({
    ...enabled("/missing/key"),OWNER_READ_INTENT_DELIVERY_ORIGIN:CLOUD
  },CLOUD,ready),/Independent owner-intent origin/);
  await assert.rejects(openConfiguredOwnerIntentDelivery({
    ...enabled("/missing/key"),OWNER_READ_INTENT_DELIVERY_ORIGIN:"http://owner.example.test"
  },CLOUD,ready),/Exact independent owner HTTPS origin/);
});

test("only an owner-owned, private, regular Ed25519 key can enable delivery",async()=>{
  const dir=await mkdtemp(path.join(tmpdir(),"cloud-owner-intent-"));
  try{
    const key=path.join(dir,"signer.pem");
    const pem=generateKeyPairSync("ed25519").privateKey.export({
      format:"pem",type:"pkcs8"
    });
    await writeFile(key,pem,{mode:0o600});
    const deliver=await openConfiguredOwnerIntentDelivery(enabled(key),CLOUD,ready);
    assert.equal(typeof deliver,"function");
    assert.equal(await deliver!({
      requestId:randomUUID(),ownerSub:"owner",clientId:"client",
      deviceId:randomUUID(),projectId:randomUUID(),origin:CLOUD,
      operation:"project_summary",expiresAtUnixMs:Date.now()-1000
    }),null,"expired read scopes cannot reach the owner authority");
    await chmod(key,0o644);
    await assert.rejects(openConfiguredOwnerIntentDelivery(enabled(key),CLOUD,ready),
      /Untrusted owner-intent signing key/);
    await chmod(key,0o600);
    const alias=path.join(dir,"hardlink.pem");
    await link(key,alias);
    await assert.rejects(openConfiguredOwnerIntentDelivery(enabled(key),CLOUD,ready),
      /Untrusted owner-intent signing key/);
    await rm(alias);
    const shortcut=path.join(dir,"symlink.pem");
    await symlink(key,shortcut);
    await assert.rejects(openConfiguredOwnerIntentDelivery(enabled(shortcut),CLOUD,ready),
      /ELOOP/);
    await assert.rejects(openConfiguredOwnerIntentDelivery({
      ...enabled(key),OWNER_READ_INTENT_DELIVERY_ORIGIN:"http://owner.example.test"
    },CLOUD,ready),/HTTPS/);
    await assert.rejects(openConfiguredOwnerIntentDelivery({
      ...enabled(key),OWNER_READ_INTENT_DELIVERY_CA_FILE:path.join(dir,"no-ca.pem")
    },CLOUD,ready),/ENOENT/);
  }finally{await rm(dir,{recursive:true,force:true});}
});
