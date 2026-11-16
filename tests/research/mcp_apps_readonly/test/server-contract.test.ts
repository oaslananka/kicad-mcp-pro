import assert from "node:assert/strict";
import test from "node:test";
import { Client, InMemoryTransport } from "@modelcontextprotocol/client";
import { createFixtureServer, RESOURCE_URI, TOOL_NAME } from "../src/server.js";

async function fixtureClient() {
  const server = createFixtureServer();
  const client = new Client({ name: "readonly-fixture-test", version: "1.0.0" }, { capabilities: {} });
  const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();
  await server.connect(serverTransport);
  await client.connect(clientTransport);
  return { client, server, close: async () => { await client.close(); await server.close(); } };
}

test("exactly one model-only read-only fixture tool declares modern UI URI", async () => {
  const x = await fixtureClient();
  try {
    const { tools } = await x.client.listTools();
    assert.equal(tools.length, 1);
    assert.equal(tools[0]?.name, TOOL_NAME);
    assert.equal((tools[0]?._meta as any)?.ui?.resourceUri, RESOURCE_URI);
    assert.deepEqual((tools[0]?._meta as any)?.ui?.visibility, ["model"]);
    assert.equal(tools[0]?.annotations?.readOnlyHint, true);
    assert.equal(tools[0]?.annotations?.destructiveHint, false);
  } finally { await x.close(); }
});

test("text and structured review are identical for UI and ordinary clients", async () => {
  const x = await fixtureClient();
  try {
    for (const [variant, expected] of [["pcb-drc", "2 errors, 1 warning"], ["schematic-erc", "1 error, 1 warning"], ["empty", "0 errors, 0 warnings"]] as const) {
      const result = await x.client.callTool({ name: TOOL_NAME, arguments: { variant } });
      assert.equal(result.isError, false);
      const text = result.content.find((c: any) => c.type === "text") as { text: string };
      assert.ok(text.text.includes(expected));
      assert.match(text.text, /Synthetic example — no live KiCad design analyzed/);
      assert.equal((result.structuredContent as any).synthetic, true);
      assert.equal((result.structuredContent as any).title.length > 0, true);
    }
  } finally { await x.close(); }
});

test("one ui:// resource returns one single-file HTML with restrictive CSP", async () => {
  const x = await fixtureClient();
  try {
    const list = await x.client.listResources();
    assert.equal(list.resources.length, 1);
    assert.equal(list.resources[0]?.uri, RESOURCE_URI);
    const response = await x.client.readResource({ uri: RESOURCE_URI });
    assert.equal(response.contents.length, 1);
    assert.equal(response.contents[0]?.mimeType, "text/html;profile=mcp-app");
    assert.match((response.contents[0] as any)?.text, /<html/i);
    assert.deepEqual((response.contents[0] as any)?._meta?.ui?.csp, {
      connectDomains: [], resourceDomains: [], frameDomains: [], baseUriDomains: []
    });
  } finally { await x.close(); }
});

test("forbid paths, uploads, extra args and unknown tools", async () => {
  const x = await fixtureClient();
  try {
    for (const args of [
      { variant: "../secret" }, { variant: "pcb-drc", path: "/tmp/secret" },
      { variant: "pcb-drc", upload: true }, { variant: "pcb-drc", url: "https://example.com" },
      { variant: ["pcb-drc"] }
    ]) {
      const result = await x.client.callTool({ name: TOOL_NAME, arguments: args });
      assert.equal(result.isError, true);
      assert.doesNotMatch(JSON.stringify(result), /secret\.kicad|\.env/);
    }
    await assert.rejects(() => x.client.callTool({ name: "write_pcb_file", arguments: {} }));
    await assert.rejects(() => x.client.readResource({ uri: "ui://kicad-mcp-pro/evil" }));
  } finally { await x.close(); }
});
