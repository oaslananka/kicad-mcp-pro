import assert from "node:assert/strict";
import {test} from "node:test";
import {ConnectorReadSequence} from "../src/connector-read-sequence.js";

test("one in-flight request per authenticated session",()=>{
  const seq=new ConnectorReadSequence();
  assert.equal(seq.reserve(),1);
  assert.equal(seq.reserve(),null);
  assert.equal(seq.complete(1),true);
  assert.equal(seq.reserve(),2);
  assert.equal(seq.complete(2),true);
});

test("unknown and replayed completion never advances the session",()=>{
  const seq=new ConnectorReadSequence();
  assert.equal(seq.reserve(),1);
  assert.equal(seq.complete(2),false);
  assert.equal(seq.reserve(),null);
  assert.equal(seq.complete(1),false);
});

test("duplicate completion cannot authorize another read",()=>{
  const seq=new ConnectorReadSequence();
  assert.equal(seq.reserve(),1);
  assert.equal(seq.complete(1),true);
  assert.equal(seq.complete(1),false);
  assert.equal(seq.reserve(),null);
});

test("closing a session fences pending responses",()=>{
  const seq=new ConnectorReadSequence();
  assert.equal(seq.reserve(),1);
  seq.close();
  assert.equal(seq.complete(1),false);
  assert.equal(seq.reserve(),null);
});

test("bounded session requires renewal instead of indefinite reads",()=>{
  const seq=new ConnectorReadSequence(2);
  assert.equal(seq.reserve(),1);
  assert.equal(seq.complete(1),true);
  assert.equal(seq.reserve(),2);
  assert.equal(seq.complete(2),true);
  assert.equal(seq.reserve(),null);
});

test("invalid session limits fail at setup",()=>{
  for(const invalid of [0,-1,1.5,NaN,Infinity,2**32]){
    assert.throws(()=>new ConnectorReadSequence(invalid),RangeError);
  }
});
