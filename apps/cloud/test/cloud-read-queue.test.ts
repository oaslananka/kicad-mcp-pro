import assert from "node:assert/strict";
import test from "node:test";
import {createCloudReadLane,runSerializedCloudRead} from "../src/cloud-read-queue.js";

function deferred<T>(){
  let resolve!:(value:T)=>void;
  let reject!:(reason?:unknown)=>void;
  const promise=new Promise<T>((res,rej)=>{resolve=res;reject=rej;});
  return {promise,resolve,reject};
}

test("readonly work on one device is FIFO, bounded, and isolated from other devices",async()=>{
  const run=createCloudReadLane(1_000,2);
  const gate=deferred<void>();
  const order:string[]=[];
  const first=run("owner:device",async()=>{
    order.push("first");await gate.promise;return "first";
  },()=>"busy");
  const second=run("owner:device",async()=>{
    order.push("second");return "second";
  },()=>"busy");
  const third=run("owner:device",async()=>{
    order.push("third");return "third";
  },()=>"busy");
  const overflow=await run("owner:device",async()=>{
    throw new Error("overflow must not dispatch");
  },()=>"busy");
  assert.equal(overflow,"busy");
  const other=await run("other:device",async()=>{
    order.push("other");return "other";
  },()=>"busy");
  assert.equal(other,"other");
  assert.deepEqual(order,["first","other"]);
  gate.resolve();
  assert.deepEqual(await Promise.all([first,second,third]),["first","second","third"]);
  assert.deepEqual(order,["first","other","second","third"]);
});

test("timed-out queued work is removed and cannot execute after release",async()=>{
  const run=createCloudReadLane(30,1);
  const gate=deferred<void>();
  let dispatched=0;
  const first=run("device",async()=>{await gate.promise;return "first";},()=>"busy");
  const expired=await run("device",async()=>{
    dispatched++;return "should-never-run";
  },()=>"busy");
  assert.equal(expired,"busy");
  gate.resolve();
  assert.equal(await first,"first");
  assert.equal(dispatched,0);
  assert.equal(await run("device",async()=>"later",()=>"busy"),"later");
});

test("failed readonly operation releases the lane for the next request",async()=>{
  const run=createCloudReadLane(1_000,1);
  const gate=deferred<void>();
  const first=run("device",async()=>{
    await gate.promise;
    throw new Error("read-only inspection failed");
  },()=>"busy");
  const second=run("device",async()=>"recovered",()=>"busy");
  gate.resolve();
  await assert.rejects(first,/inspection failed/);
  assert.equal(await second,"recovered");
});

test("inventory and owner identity isolate read queues",async()=>{
  const a={};
  const b={};
  const gate=deferred<void>();
  const pending=runSerializedCloudRead(a,"owner-A","device",async()=>{
    await gate.promise;return "first";
  },()=>"busy");
  const independent=await Promise.all([
    runSerializedCloudRead(b,"owner-A","device",async()=>"other-inventory",()=>"busy"),
    runSerializedCloudRead(a,"owner-B","device",async()=>"other-owner",()=>"busy"),
    runSerializedCloudRead(a,"owner-A","other-device",async()=>"other-device",()=>"busy")
  ]);
  assert.deepEqual(independent,["other-inventory","other-owner","other-device"]);
  gate.resolve();
  assert.equal(await pending,"first");
});
test("default READ queue survives a normal GUI operation lasting more than four seconds",async()=>{
  const inventory={};
  const gate=deferred<void>();
  let secondExecuted=false;
  const first=runSerializedCloudRead(inventory,"owner","device",async()=>{
    await gate.promise;
    return "first";
  },()=>"busy");
  const second=runSerializedCloudRead(inventory,"owner","device",async()=>{
    secondExecuted=true;
    return "second";
  },()=>"busy");
  // Real KiCad READ calls take roughly seven seconds end-to-end; the prior
  // four-second queue timeout rejected the second request prematurely.
  await new Promise<void>(resolve=>setTimeout(resolve,5_200));
  gate.resolve();
  assert.equal(await first,"first");
  assert.equal(await second,"second");
  assert.equal(secondExecuted,true);
});
