import assert from "node:assert/strict";
import { test } from "node:test";
import { inIsolatedDatabase } from "./isolated-db.js";
import { PgUsage } from "../src/usage.js";
import { extractToolCall, callStatusFromResponse } from "../src/usage.js";
import pg from "pg";

const url = process.env.TEST_DATABASE_URL;

test("usage extraction only records deterministic tool-call outcomes", () => {
  // A JSON-RPC tool call with a named tool is extractable.
  assert.deepEqual(
    extractToolCall(JSON.stringify({
      jsonrpc: "2.0", id: 7, method: "tools/call",
      params: { name: "list_projects", arguments: {} }
    })),
    { id: 7, tool: "list_projects" }
  );
  // A batch of one call is also extractable.
  assert.deepEqual(
    extractToolCall(JSON.stringify([
      { jsonrpc: "2.0", id: "a", method: "tools/call", params: { name: "get_service_status" } }
    ])),
    { id: "a", tool: "get_service_status" }
  );
  // Non-tool traffic, malformed payloads and oversized names record nothing.
  assert.equal(extractToolCall(JSON.stringify({ jsonrpc: "2.0", id: 1, method: "tools/list" })), null);
  assert.equal(extractToolCall("not json"), null);
  assert.equal(extractToolCall(JSON.stringify({ jsonrpc: "2.0", id: 1, method: "tools/call" })), null);
  assert.equal(extractToolCall(
    JSON.stringify({ jsonrpc: "2.0", id: 1, method: "tools/call", params: { name: "x".repeat(200) } })
  ), null);
  // Status mapping: protocol errors are denials, isError results are errors.
  assert.equal(callStatusFromResponse(
    JSON.stringify({ jsonrpc: "2.0", id: 7, error: { code: -32602, message: "bad" } }), 7),
    "denied");
  assert.equal(callStatusFromResponse(
    JSON.stringify({ jsonrpc: "2.0", id: 7, result: { isError: true, content: [] } }), 7),
    "error");
  assert.equal(callStatusFromResponse(
    JSON.stringify({ jsonrpc: "2.0", id: 7, result: { content: [] } }), 7),
    "success");
  // A response that cannot be matched to the request records nothing.
  assert.equal(callStatusFromResponse("not json", 7), null);
  assert.equal(callStatusFromResponse(JSON.stringify({ jsonrpc: "2.0", id: 8, result: {} }), 7), null);
});

test("usage recorder stores bounded observations and aggregates honestly", { skip: !url }, async () => {
  await inIsolatedDatabase(url!, ["022_usage_and_owner_api.pgsql"], async db => {
    const usage = new PgUsage(db);
    // Bounded, validated inputs only.
    await usage.record("owner-a", "client-a", "list_projects", "success");
    await usage.record("owner-a", "client-a", "list_projects", "success");
    await usage.record("owner-a", "client-a", "get_project_drc_counts", "denied");
    await usage.record("owner-a", "client-b", "list_devices", "error");
    await usage.record("owner-b", "client-a", "list_projects", "success");
    // Invalid values are refused, never coerced into fabricated rows.
    await usage.record("owner-a", "", "list_projects", "success");
    await usage.record("owner-a", "client-a", "", "success");
    await usage.record("owner-a", "client-a", "list_projects", "quota" as never);

    const summary = await usage.summary("owner-a");
    assert.ok(summary);
    assert.equal(summary.totalCalls, 4);
    assert.deepEqual(summary.byTool, [
      { tool: "list_projects", count: 2 },
      { tool: "get_project_drc_counts", count: 1 },
      { tool: "list_devices", count: 1 }
    ]);
    assert.deepEqual(summary.byClient, [
      { clientId: "client-a", count: 3 },
      { clientId: "client-b", count: 1 }
    ]);
    assert.deepEqual(summary.byStatus, [
      { status: "success", count: 2 },
      { status: "denied", count: 1 },
      { status: "error", count: 1 }
    ]);
    // Recent events are timestamped, owner-scoped and safe-field only.
    const recent = await usage.recent("owner-a", 3);
    assert.equal(recent.length, 3);
    for (const event of recent) {
      assert.ok(event.id > 0);
      assert.ok(typeof event.at === "string" && !Number.isNaN(Date.parse(event.at)));
      assert.deepEqual(Object.keys(event).sort(),
        ["at", "clientId", "id", "status", "tool"]);
    }
    // Unknown owners have no data — never a synthetic zero-quota view.
    const none = await usage.summary("owner-unknown");
    assert.equal(none, null);
    assert.deepEqual(await usage.recent("owner-unknown", 10), []);
  });
});
