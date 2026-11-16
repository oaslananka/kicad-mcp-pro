/**
 * Independent @modelcontextprotocol/ext-tasks 0.2.3 requester against the
 * disposable Python Tasks 2026-07-28 loopback fixture.
 * Test-only: no production MCP, KiCad or credentials.
 */
import assert from "node:assert/strict";
import { withTasks, resultFromTaskOutcome } from "@modelcontextprotocol/ext-tasks/client";

const [endpoint, mode] = process.argv.slice(2);
const testToken = process.env.MCP_TASKS_TEST_TOKEN;
if (!endpoint?.startsWith("http://127.0.0.1:") || !testToken) {
  throw new Error("A loopback endpoint and ephemeral test credential are required");
}
let nextId = 1;
const methods = [];
const port = {
  endpointId: "research-only-2026-tasks",
  taskCapabilities: { generation: "v2", capabilities: {} },
  invalidated: false,
  onServerRequest() { return () => {}; },
  onNotification() { return () => {}; },
  onInvalidated() { return () => {}; },
  async dispatch(request, options) {
    const method = request.method;
    const params = request.params ?? {};
    const name = method === "tools/call"
      ? params.name
      : options?.context?.headers?.["Mcp-Name"];
    if (method.startsWith("tasks/")) {
      assert.equal(name, params.taskId, "official requester must route tasks by Mcp-Name");
    }
    const body = { jsonrpc: "2.0", id: nextId++, method, params };
    const response = await fetch(endpoint, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${testToken}`,
        "Mcp-Method": method,
        ...(name === undefined ? {} : { "Mcp-Name": name }),
      },
      body: JSON.stringify(body),
      signal: options?.signal,
    });
    assert.equal(response.status, 200, `HTTP ${response.status} on ${method}`);
    const packet = await response.json();
    assert.equal(packet.jsonrpc, "2.0");
    assert.equal(packet.id, body.id);
    methods.push(method);
    return packet.error
      ? { kind: "error", error: packet.error }
      : { kind: "result", result: packet.result };
  },
};

const session = withTasks(port, {
  tools: { currentTool() { return undefined; } },
  maxInputRounds: 2,
  async onInputRequest(request) {
    assert.equal(request.kind, "elicitation");
    return { action: "accept", content: { ack: true } };
  },
});

try {
  if (mode === "sync") {
    const ordinary = await port.dispatch({
      method: "tools/call",
      params: { name: "synthetic_drc_review", arguments: {} },
    });
    assert.equal(ordinary.kind, "result");
    assert.equal(ordinary.result.resultType, "complete");
    assert.equal(ordinary.result.isError, false);
    assert.equal("taskId" in ordinary.result, false);
  } else {
    const arguments_ = {
      ...(mode === "input" ? { requireInput: true } : {}),
      ...(mode === "toolerror" ? { simulateError: true } : {}),
    };
    const execution = await session.callTool("synthetic_erc_review", arguments_);
    assert.equal(execution.kind, "task");
    assert.ok(execution.handle.taskId.length >= 32);
    if (mode === "cancel") {
      await execution.cancel();
      const state = await session.task(execution.handle.taskId).snapshot();
      assert.equal(state.status, "cancelled");
    } else if (mode === "expired") {
      const expired = await execution.settle();
      assert.equal(expired.outcome.status, "failed");
    } else {
      const settled = await execution.settle();
      assert.equal(settled.outcome.status, "completed");
      const result = resultFromTaskOutcome(settled.outcome);
      assert.equal(result.isError, mode === "toolerror");
      assert.ok(result.content[0].text.startsWith("SYNTHETIC"));
      if (mode === "input") assert.ok(methods.includes("tasks/update"));
    }
  }
  assert.ok(methods.includes("tools/call"));
  if (mode !== "sync") assert.ok(methods.some((method) => method.startsWith("tasks/")));
  console.log(JSON.stringify({ mode, result: "PASS", methods }));
} finally {
  await session.close();
}
