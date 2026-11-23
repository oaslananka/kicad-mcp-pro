import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import test from "node:test";

const dashboard=readFileSync(new URL("../../src/kicad_mcp/web/dashboard.py",import.meta.url),"utf8");

test("local setup wizard distinguishes backend health from real AI-client MCP connectivity",()=>{
  assert.match(dashboard,/aria-label="Check local server health only"/);
  assert.match(dashboard,/>Check server health<\/button>/);
  assert.doesNotMatch(dashboard,/aria-label="Test MCP backend connection and health"/);
  assert.match(dashboard,/make a real MCP request in your AI client/);
  const fn=/function testConnection\(\)\s*\{([\s\S]*?)\n\}/.exec(dashboard)?.[1];
  assert.ok(fn);
  assert.match(fn,/fetch\('\/api\/health'\)/);
  assert.match(fn,/This verifies the local server only/);
  assert.doesNotMatch(fn,/AI client connection verified/);
});

test("wizard announces backend health results without implying user task completion",()=>{
  assert.match(dashboard,/id="testResult"[^>]+role="status"[^>]+aria-live="polite"/);
  assert.match(dashboard,/Local server health check failed/);
  assert.match(dashboard,/Local server health unavailable/);
});
