import assert from "node:assert/strict";
import {test} from "node:test";
import {CONNECTOR_CHALLENGE_TTL_MS} from "../src/connector-challenge-window.js";

test("device and session challenges allow ten seconds of clock skew within the signed Connector limit",()=>{
  const serverNowMs=1_800_000_000_000;
  const clientNowMs=serverNowMs-10_000;
  const pythonOfflineMaximumMs=60_000;
  const expiryMs=serverNowMs+CONNECTOR_CHALLENGE_TTL_MS;
  assert.ok(expiryMs>=serverNowMs+30_000,"challenge remains usable on normal networks");
  assert.ok(expiryMs<=clientNowMs+pythonOfflineMaximumMs,
    "database issue time must leave skew headroom under the unchanged local 60s bound");
});
