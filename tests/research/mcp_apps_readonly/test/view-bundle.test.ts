import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { Script } from "node:vm";
import test from "node:test";

test("bundled single-file View is exactly one document with executable JavaScript syntax", () => {
  const html = readFileSync("dist/view.html", "utf8");
  assert.equal((html.match(/<!doctype html>/gi) ?? []).length, 1);
  assert.equal((html.match(/<script>/gi) ?? []).length, 1);
  assert.equal((html.match(/<\/script>/gi) ?? []).length, 1);
  const code = html.split("<script>")[1]?.split("</script>")[0];
  assert.ok(code);
  assert.doesNotThrow(() => new Script(code));
});
