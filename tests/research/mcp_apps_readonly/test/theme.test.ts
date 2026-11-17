import assert from "node:assert/strict";
import test from "node:test";
import { parseHTML } from "linkedom";
import { applyHostTheme } from "../src/theme.js";

test("explicit host theme wins over device preference", () => {
  const { document } = parseHTML("<html><body></body></html>");
  applyHostTheme(document.documentElement, "dark");
  assert.equal(document.documentElement.getAttribute("data-theme"), "dark");
  applyHostTheme(document.documentElement, "light");
  assert.equal(document.documentElement.getAttribute("data-theme"), "light");
});

test("missing host theme does not force light (retains device dark preference)", () => {
  const { document } = parseHTML("<html><body></body></html>");
  applyHostTheme(document.documentElement, "light");
  applyHostTheme(document.documentElement, undefined);
  assert.equal(document.documentElement.hasAttribute("data-theme"), false);
});
