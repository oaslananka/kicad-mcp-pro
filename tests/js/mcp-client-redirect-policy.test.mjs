import assert from "node:assert/strict";
import { createServer } from "node:http";
import { test } from "node:test";
import { StreamableHTTPClientTransport } from "@modelcontextprotocol/client";

const listen = server => new Promise((resolve, reject) => {
  server.once("error", reject);
  server.listen(0, "127.0.0.1", () => {
    server.removeListener("error", reject);
    resolve(`http://127.0.0.1:${server.address().port}/mcp`);
  });
});

test("MCP HTTP client refuses cross-origin 307 redirects by default", async t => {
  let unexpectedRequests = 0;
  const foreign = createServer((req, res) => {
    unexpectedRequests++;
    req.resume();
    res.writeHead(200, { "content-type": "application/json" });
    res.end('{"jsonrpc":"2.0","id":1,"result":{}}');
  });
  t.after(() => {
    foreign.closeAllConnections();
    foreign.close();
  });
  const foreignUrl = await listen(foreign);
  const origin = createServer((req, res) => {
    req.resume();
    res.writeHead(307, { location: foreignUrl });
    res.end();
  });
  t.after(() => {
    origin.closeAllConnections();
    origin.close();
  });
  const originUrl = await listen(origin);
  const transport = new StreamableHTTPClientTransport(new URL(originUrl), {
    requestInit: { headers: { "X-API-Key": "synthetic-test-only" } }
  });
  t.after(() => transport.close());
  await transport.start();
  await transport.send(
    { jsonrpc: "2.0", id: 1, method: "ping" },
    { requestSignal: AbortSignal.timeout(2500) }
  ).catch(() => {});
  assert.equal(unexpectedRequests, 0,
    "Default SDK transport must never resend an MCP request or its headers to a different origin");
});
