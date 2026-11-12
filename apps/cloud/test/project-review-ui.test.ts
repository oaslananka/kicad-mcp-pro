import assert from "node:assert/strict";
import {test} from "node:test";
import {readFileSync} from "node:fs";
import {fileURLToPath} from "node:url";
const template=readFileSync(fileURLToPath(new URL("../src/project-review.html",import.meta.url)),"utf8");
const script=readFileSync(fileURLToPath(new URL("../src/project-review-app.ts",import.meta.url)),"utf8");

test("portable MCP App presents an accessible, host-adaptive project review",()=>{
  assert.match(template,/name="viewport"/);
  assert.match(template,/role="status" aria-live="polite"/);
  assert.match(template,/id="details"[^>]*hidden/);
  assert.match(template,/id="project-name"/);
  assert.match(template,/id="project-connection"/);
  assert.match(template,/id="refresh"[^>]*disabled/);
  assert.match(template,/@media\s*\(prefers-color-scheme:\s*light\)/);
  assert.match(template,/--color-text-primary/);
  assert.match(template,/min-height:\s*44px/);
  assert.doesNotMatch(template,/@import|url\(https?:/i);
  assert.match(script,/new App\(/);
  assert.match(script,/\.ontoolresult\s*=/);
  assert.match(script,/\.callServerTool\(/);
  assert.match(script,/\.textContent\s*=/);
  assert.doesNotMatch(script,/innerHTML\s*=/);
});
