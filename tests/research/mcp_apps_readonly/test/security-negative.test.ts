import assert from "node:assert/strict";
import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import { createServer as createNetServer } from "node:net";
import { request as httpRequest } from "node:http";
import { before, after, test } from "node:test";

let port: number;
let child: ChildProcessWithoutNullStreams;

async function unusedPort(): Promise<number> {
  const server = createNetServer();
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const address = server.address();
  if (!address || typeof address === "string") throw new Error("Port unavailable");
  const value = address.port;
  await new Promise<void>((resolve) => server.close(() => resolve()));
  return value;
}
function request(method: string, headers: Record<string, string> = {}, body = "") {
  return new Promise<{ status: number; headers: Record<string,string | string[] | undefined> }>((resolve, reject) => {
    const req = httpRequest({
      hostname: "127.0.0.1", port, path: "/mcp", method,
      headers: { ...headers, ...(body ? { "Content-Length": String(Buffer.byteLength(body)) } : {}) },
    }, (res) => {
      res.resume();
      res.on("end", () => resolve({ status: res.statusCode ?? 0, headers: res.headers }));
    });
    req.on("error", reject);
    req.end(body);
  });
}
before(async () => {
  port = await unusedPort();
  child = spawn(process.execPath, ["dist/node/src/main.js"], {
    cwd: process.cwd(), env: { ...process.env, PORT: String(port) }, stdio: ["pipe", "pipe", "pipe"],
  });
  await new Promise<void>((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error("Timed out waiting for loopback fixture")), 10_000);
    child.stdout.on("data", (chunk: Buffer) => {
      if (String(chunk).includes("listening")) { clearTimeout(timer); resolve(); }
    });
    child.on("exit", (code) => { clearTimeout(timer); reject(new Error(`Fixture exited: ${code}`)); });
  });
});
after(() => { if (child) child.kill(); });

test("only explicit reference host origin can access fixture through CORS", async () => {
  const response = await request("OPTIONS", {
    Host: `127.0.0.1:${port}`,
    Origin: "http://localhost:8080",
    "Access-Control-Request-Method": "POST",
    "Access-Control-Request-Headers": "content-type,mcp-protocol-version",
  });
  assert.equal(response.status, 204);
  assert.equal(response.headers["access-control-allow-origin"], "http://localhost:8080");
  assert.match(String(response.headers["access-control-allow-headers"]), /mcp-protocol-version/i);
});

test("reject external host, external origin and app sandbox origin", async () => {
  const evilHost = await request("POST", { Host: "evil.example", "Content-Type": "application/json" }, "{}");
  assert.equal(evilHost.status, 403);
  for (const origin of ["https://evil.example", "http://localhost:8081"]) {
    const denied = await request("POST", {
      Host: `127.0.0.1:${port}`, Origin: origin, "Content-Type": "application/json",
    }, "{}");
    assert.equal(denied.status, 403);
    assert.equal(denied.headers["access-control-allow-origin"], undefined);
  }
});

test("reject oversized input before invoking any MCP tool", async () => {
  const oversized = await request("POST", {
    Host: `127.0.0.1:${port}`, "Content-Type": "application/json",
  }, JSON.stringify({ method: "tools/call", arguments: "x".repeat(5 * 1024) }));
  assert.equal(oversized.status, 413);
});
