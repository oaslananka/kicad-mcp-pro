import assert from "node:assert/strict";
import test from "node:test";
import {retryReadOnlyCatalog} from "../src/read-catalog-refresh.js";

test("retry only signed READ discovery until a fresh catalog responds",async()=>{
  let attempts=0;
  const value={tools:[{name:"pcb_get_footprints"}]};
  const catalog=await retryReadOnlyCatalog(async()=>{
    attempts++;
    if(attempts===1)throw new Error("signed session rotated");
    if(attempts===2)return null;
    return value;
  },[1,2,3],100);
  assert.equal(catalog,value);
  assert.equal(attempts,3);
});

test("permanent unavailability is capped by attempts and returns no fabricated catalog",async()=>{
  let attempts=0;
  const catalog=await retryReadOnlyCatalog(async()=>{
    attempts++;
    return null;
  },[1,2],100);
  assert.equal(catalog,null);
  assert.equal(attempts,3);
});

test("elapsed budget prevents repeated discovery after a long failed call",async()=>{
  let attempts=0;
  const catalog=await retryReadOnlyCatalog(async()=>{
    attempts++;
    await new Promise<void>(resolve=>setTimeout(resolve,12));
    return null;
  },[1,1,1],4);
  assert.equal(catalog,null);
  assert.equal(attempts,1);
});

test("valid empty catalog is authoritative and is not retried",async()=>{
  let attempts=0;
  const expected={tools:[],nextOffset:null};
  const catalog=await retryReadOnlyCatalog(async()=>{
    attempts++;
    return expected;
  },[1,2],100);
  assert.equal(catalog,expected);
  assert.equal(attempts,1);
});
