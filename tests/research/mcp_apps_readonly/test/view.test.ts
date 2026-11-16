import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";
import { parseHTML } from "linkedom";
import { renderReview } from "../src/view.js";

const fixture = (name: string): unknown =>
  JSON.parse(readFileSync(path.join(process.cwd(), "fixtures", name), "utf8"));

function setup() {
  const { document, window } = parseHTML('<html><body><main id="review-root"></main></body></html>');
  const root = document.getElementById("review-root") as unknown as HTMLElement;
  return { root, window };
}

test("renders useful project summary and synthetic disclaimer", () => {
  const { root } = setup();
  renderReview(fixture("pcb-drc.json"), root);
  const text = root.textContent ?? "";
  assert.match(text, /Synthetic example — no live KiCad design analyzed/);
  assert.match(text, /Sensor Controller Example/);
  assert.match(text, /DRC/);
  assert.match(text, /2/);
  assert.equal(root.querySelectorAll("[data-finding]").length, 3);
  assert.equal(root.querySelectorAll("button[aria-pressed]").length, 3);
});

test("local severity filtering is keyboard-friendly and never invokes tools", () => {
  const { root, window } = setup();
  renderReview(fixture("pcb-drc.json"), root);
  const warnings = root.querySelector("button[data-filter='warning']") as HTMLButtonElement;
  assert.equal(warnings.tagName.toLowerCase(), "button");
  assert.equal(warnings.getAttribute("aria-pressed"), "false");
  warnings.dispatchEvent(new window.Event("click", { bubbles: true }));
  assert.equal(warnings.getAttribute("aria-pressed"), "true");
  assert.equal(root.querySelectorAll("[data-finding]").length, 1);
  assert.match(root.textContent ?? "", /Silkscreen text/);
  assert.doesNotMatch(root.textContent ?? "", /Track-to-pad clearance/);
});

test("empty and malformed reports show explicit safe states", () => {
  const { root } = setup();
  renderReview(fixture("empty.json"), root);
  assert.match(root.textContent ?? "", /No findings/);
  renderReview({ synthetic: true, title: "Forged", projectPath: "/secrets" }, root);
  assert.match(root.textContent ?? "", /Review unavailable/);
  assert.doesNotMatch(root.textContent ?? "", /secrets|Forged/);
});

test("hostile text stays literal DOM text, never produces links or active HTML", () => {
  const { root } = setup();
  const data = fixture("empty.json") as Record<string, any>;
  data.findings = [{ code: "injection", severity: "warning", message: '<img src=x onerror=alert(1)> https://evil.example' }];
  data.summary.warnings = 1;
  renderReview(data, root);
  assert.match(root.textContent ?? "", /<img src=x onerror/);
  assert.equal(root.querySelectorAll("img,script,a,iframe,form").length, 0);
});

test("new result clears previous findings and count", () => {
  const { root } = setup();
  renderReview(fixture("pcb-drc.json"), root);
  renderReview(fixture("schematic-erc.json"), root);
  assert.equal(root.querySelectorAll("[data-finding]").length, 2);
  assert.match(root.textContent ?? "", /Power Supply Example/);
  assert.doesNotMatch(root.textContent ?? "", /Sensor Controller Example|Track-to-pad/);
});
