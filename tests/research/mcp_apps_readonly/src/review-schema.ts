export const MAX_REPORT_BYTES = 64 * 1024;
export const MAX_FINDINGS = 50;

export type Severity = "error" | "warning";
export type ReviewFinding = Readonly<{ code: string; severity: Severity; message: string }>;
export type ReviewFixture = Readonly<{
  synthetic: true;
  title: string;
  kind: "pcb" | "schematic";
  category: "DRC" | "ERC";
  summary: Readonly<{ errors: number; warnings: number }>;
  findings: readonly ReviewFinding[];
}>;

function record(value: unknown, keys: readonly string[]): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error("Invalid report object");
  }
  const obj = value as Record<string, unknown>;
  if (Object.keys(obj).some((key) => !keys.includes(key)) ||
      keys.some((key) => !Object.hasOwn(obj, key))) {
    throw new Error("Invalid or unsupported report field");
  }
  return obj;
}

function safeString(value: unknown, maxLength: number): string {
  if (typeof value !== "string" || !value.trim()) {
    throw new Error("Invalid display string");
  }
  if (value.length > maxLength || /[\u0000-\u001f\u007f]/u.test(value)) {
    throw new Error("Display string exceeds limit");
  }
  return value;
}

function nonnegativeCount(value: unknown): number {
  if (typeof value !== "number" || !Number.isSafeInteger(value) || value < 0 || value > MAX_FINDINGS) {
    throw new Error("Invalid report count limit");
  }
  return value;
}

function isSafeFindingCode(code: string): boolean {
  // Bounded (<= 64 chars) ASCII allowlist: no regex or attacker-controlled pattern.
  for (let index = 0; index < code.length; index++) {
    const point = code.charCodeAt(index);
    const isDigit = point >= 48 && point <= 57;
    const isLowercaseLetter = point >= 97 && point <= 122;
    const isInternalHyphen = point === 45 && index > 0;
    if (!isDigit && !isLowercaseLetter && !isInternalHyphen) return false;
  }
  return true;
}
export function parseReviewFixture(input: unknown): ReviewFixture {
  let encoded: string;
  try { encoded = JSON.stringify(input); } catch { throw new Error("Invalid report JSON"); }
  if (typeof encoded !== "string" || new TextEncoder().encode(encoded).byteLength > MAX_REPORT_BYTES) {
    throw new Error("Report byte limit exceeded");
  }
  const obj = record(input, ["synthetic", "title", "kind", "category", "summary", "findings"]);
  if (obj.synthetic !== true) throw new Error("Invalid synthetic marker");
  const title = safeString(obj.title, 128);
  if (obj.kind !== "pcb" && obj.kind !== "schematic") throw new Error("Invalid project kind");
  const category = obj.kind === "pcb" ? "DRC" : "ERC";
  if (obj.category !== category) throw new Error("Invalid review category");
  const summary = record(obj.summary, ["errors", "warnings"]);
  const errors = nonnegativeCount(summary.errors);
  const warnings = nonnegativeCount(summary.warnings);
  if (!Array.isArray(obj.findings)) throw new Error("Invalid findings");
  if (obj.findings.length > MAX_FINDINGS) throw new Error("Findings limit exceeded");
  const findings: ReviewFinding[] = obj.findings.map((entry: unknown) => {
    const finding = record(entry, ["code", "severity", "message"]);
    const code = safeString(finding.code, 64);
    if (!isSafeFindingCode(code)) throw new Error("Invalid finding code");
    if (finding.severity !== "error" && finding.severity !== "warning") {
      throw new Error("Invalid finding severity");
    }
    return { code, severity: finding.severity, message: safeString(finding.message, 512) };
  });
  if (errors !== findings.filter((entry) => entry.severity === "error").length ||
      warnings !== findings.filter((entry) => entry.severity === "warning").length) {
    throw new Error("Finding counts mismatch");
  }
  return { synthetic: true, title, kind: obj.kind, category, summary: { errors, warnings }, findings };
}

export function formatTextReview(data: ReviewFixture): string {
  const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;
  const header = `${data.title} (${data.kind.toUpperCase()} / ${data.category}): ${plural(data.summary.errors, "error")}, ${plural(data.summary.warnings, "warning")}.`;
  const findings = data.findings.length
    ? data.findings.map((f) => `- [${f.severity.toUpperCase()}] ${f.code}: ${f.message}`).join("\n")
    : "No findings.";
  return `Synthetic example — no live KiCad design analyzed.\n${header}\n${findings}`;
}
