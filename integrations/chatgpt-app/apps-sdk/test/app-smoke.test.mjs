import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { readFile } from "node:fs/promises";
import net from "node:net";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StreamableHTTPClientTransport } from "@modelcontextprotocol/sdk/client/streamableHttp.js";

const APP_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const EXPECTED_TOOLS = [
  "analyze_uploaded_kicad_project",
  "explain_drc_report",
  "explain_erc_report",
  "generate_agent_config",
  "generate_manufacturing_readiness_report",
  "search_kicad_knowledge",
];
const WIDGETS = [
  "kicad-dashboard.html",
  "project-review.html",
  "manufacturing-report.html",
];

async function freePort() {
  return await new Promise((resolve, reject) => {
    const server = net.createServer();
    server.unref();
    server.on("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      const port = typeof address === "object" && address ? address.port : 0;
      server.close((error) => error ? reject(error) : resolve(port));
    });
  });
}

async function startServer() {
  const port = await freePort();
  const child = spawn(process.execPath, ["dist/server.js"], {
    cwd: APP_ROOT,
    env: { ...process.env, HOST: "127.0.0.1", PORT: String(port) },
    stdio: ["ignore", "pipe", "pipe"],
  });
  let output = "";
  child.stdout.on("data", (chunk) => { output += chunk.toString(); });
  child.stderr.on("data", (chunk) => { output += chunk.toString(); });

  const deadline = Date.now() + 10_000;
  while (Date.now() < deadline) {
    if (child.exitCode !== null) {
      throw new Error(`ChatGPT app exited before startup:\n${output}`);
    }
    try {
      const response = await fetch(`http://127.0.0.1:${port}/`);
      if (response.ok) return { child, port };
    } catch {
      // Startup race; retry until the deadline.
    }
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  child.kill();
  throw new Error(`ChatGPT app did not start:\n${output}`);
}

async function stopServer(child) {
  if (child.exitCode !== null) return;
  child.kill();
  await Promise.race([
    new Promise((resolve) => child.once("exit", resolve)),
    new Promise((resolve) => setTimeout(resolve, 3_000)),
  ]);
}

async function connect(port) {
  const client = new Client({ name: "chatgpt-app-smoke", version: "1.0.0" });
  const transport = new StreamableHTTPClientTransport(
    new URL(`http://127.0.0.1:${port}/mcp`),
  );
  await client.connect(transport);
  return client;
}

async function verifyPublicSafeContract(port, packageMetadata) {
  const client = await connect(port);
  try {
    assert.deepEqual(client.getServerVersion(), {
      name: "KiCad MCP Pro",
      version: packageMetadata.version,
    });

    const listed = await client.listTools();
    assert.deepEqual(listed.tools.map((tool) => tool.name).sort(), EXPECTED_TOOLS);
    for (const tool of listed.tools) {
      assert.equal(tool.annotations?.readOnlyHint, true, `${tool.name} must be read-only`);
      assert.equal(tool.annotations?.destructiveHint, false, `${tool.name} must be non-destructive`);
      assert.equal(tool.annotations?.idempotentHint, true, `${tool.name} must be idempotent`);
      assert.equal(
        tool.annotations?.openWorldHint,
        tool.name === "search_kicad_knowledge",
        `${tool.name} open-world annotation drifted`,
      );
    }

    const drc = await client.callTool({
      name: "explain_drc_report",
      arguments: { reportText: "[error] clearance: track too close" },
    });
    const drcText = drc.content?.find((item) => item.type === "text")?.text ?? "";
    assert.match(drcText, /DRC Report Summary/);
    assert.match(drcText, /Errors:\*\* 1/);
  } finally {
    await client.close();
  }

  for (const widget of WIDGETS) {
    const response = await fetch(`http://127.0.0.1:${port}/widgets/${widget}`);
    assert.equal(response.status, 200, `${widget} must be served`);
    const body = await response.text();
    assert.match(body, /<!DOCTYPE html>/i);
    assert.match(body, /postMessage|mcp-tool-result/i);
  }
}

test("public-safe ChatGPT app contract survives process restart", async () => {
  const packageMetadata = JSON.parse(
    await readFile(path.join(APP_ROOT, "package.json"), "utf8"),
  );

  const first = await startServer();
  try {
    await verifyPublicSafeContract(first.port, packageMetadata);
  } finally {
    await stopServer(first.child);
  }

  const second = await startServer();
  try {
    const client = await connect(second.port);
    await client.close();
  } finally {
    await stopServer(second.child);
  }
});
