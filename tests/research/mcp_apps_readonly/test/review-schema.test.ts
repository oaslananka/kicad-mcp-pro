import { readFileSync } from "node:fs";
import path from "node:path";
import assert from "node:assert/strict";
import test from "node:test";
import { parseReviewFixture, formatTextReview, MAX_REPORT_BYTES, MAX_FINDINGS } from "../src/review-schema.js";

const load = (name: string): unknown =>
  JSON.parse(readFileSync(path.join(process.cwd(), "fixtures", name), "utf8"));

test("PCB/DRC review stays useful as text without UI", () => {
  const review = parseReviewFixture(load("pcb-drc.json"));
  assert.equal(review.category, "DRC");
  assert.deepEqual(review.summary, { errors: 2, warnings: 1 });
  assert.equal(review.findings.length, 3);
  const text = formatTextReview(review);
  assert.match(text, /Synthetic example â€” no live KiCad design analyzed/);
  assert.match(text, /2 errors, 1 warning/);
  assert.match(text, /\[ERROR\] clearance:/);
  assert.match(text, /\[WARNING\] silkscreen:/);
});

test("schematic/ERC and empty fixture show genuine counts", () => {
  const erc = parseReviewFixture(load("schematic-erc.json"));
  assert.equal(erc.category, "ERC");
  assert.match(formatTextReview(erc), /1 error, 1 warning/);
  const empty = parseReviewFixture(load("empty.json"));
  assert.deepEqual(empty.findings, []);
  assert.match(formatTextReview(empty), /No findings\./);
});

test("wrong types, forged synthetic flag and unknown fields are rejected", () => {
  const data = load("empty.json") as Record<string, unknown>;
  for (const item of [
    { ...data, synthetic: false },
    { ...data, projectPath: "C:/hidden/project.kicad_pro" },
    { ...data, title: 23 },
    { ...data, kind: "unknown" },
    { ...data, summary: { errors: -1, warnings: 0 } },
    { ...data, findings: null },
    { ...data, summary: { errors: Infinity, warnings: 0 } }
  ]) {
    assert.throws(() => parseReviewFixture(item), /Invalid|unsupported|limit|mismatch/);
  }
});

test("inconsistent severity totals and oversized fields fail closed", () => {
  const data = load("pcb-drc.json") as Record<string, any>;
  assert.throws(() => parseReviewFixture({ ...data, summary: { errors: 0, warnings: 0 } }), /mismatch/);
  assert.throws(() => parseReviewFixture({ ...data, title: "x".repeat(129) }), /limit/);
  assert.throws(() => parseReviewFixture({ ...data, findings: Array(MAX_FINDINGS + 1).fill(data.findings[0]) }), /limit/);
  assert.throws(() => parseReviewFixture({ ...data, findings: [{ severity: "error", code: "x", message: "<".repeat(MAX_REPORT_BYTES) }] }), /limit/);
});

test("literal HTML and Unicode remain ordinary text without generated links", () => {
  const data = load("empty.json") as Record<string, any>;
  data.findings = [{ code: "xss", severity: "warning", message: '<img src=x onerror=alert(1)> https://evil.example' }];
  data.summary.warnings = 1;
  const text = formatTextReview(parseReviewFixture(data));
  assert.match(text, /<img src=x onerror/);
  assert.match(text, /https:\/\/evil\.example/);
  assert.doesNotMatch(text, /<a href=/);
});
test("schema parsing works inside browser sandbox without Node Buffer", () => {
  const original = globalThis.Buffer;
  try {
    (globalThis as unknown as { Buffer?: typeof Buffer }).Buffer = undefined;
    const result = parseReviewFixture(load("empty.json"));
    assert.equal(result.summary.errors, 0);
  } finally {
    globalThis.Buffer = original;
  }
});
test("finding codes use a bounded ASCII allowlist, without regex backtracking", () => {
  const original = load("empty.json") as Record<string, any>;
  const item = { code: "valid-12", severity: "warning", message: "Synthetic warning." };
  const report = { ...original, summary: { errors: 0, warnings: 1 }, findings: [item] };
  assert.equal(parseReviewFixture(report).findings[0]?.code, "valid-12");
  for (const code of ["-leading", "Upper", "a_b", "a b", "<script>", "é", "??"]) {
    assert.throws(
      () => parseReviewFixture({ ...report, findings: [{ ...item, code }] }),
      /Invalid finding code/,
      code,
    );
  }
});
