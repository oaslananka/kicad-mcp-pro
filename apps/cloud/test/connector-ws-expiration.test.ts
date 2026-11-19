import assert from "node:assert/strict";
import {test} from "node:test";
import {connectorExpiryDisposition} from "../src/connector-ws.js";

test("normal ready-session lease expiration is not an owner policy denial",()=>{
  assert.deepEqual(connectorExpiryDisposition("ready"),
    {code:1000,reason:"session_expired"});
  assert.deepEqual(connectorExpiryDisposition("device_challenge"),
    {code:1008,reason:"policy"});
  assert.deepEqual(connectorExpiryDisposition("session_challenge"),
    {code:1008,reason:"policy"});
});
