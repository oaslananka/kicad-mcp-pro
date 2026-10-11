import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { chmodSync, existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { delimiter, join, resolve } from "node:path";
import test from "node:test";

const installer = resolve("integrations/common/install-kicad-mcp.mjs");

function fakeBinary(dir, response = "✓ Config written to /safe/test.json") {
  const windows = process.platform === "win32";
  const binary = join(dir, windows ? "kicad-mcp-pro.cmd" : "kicad-mcp-pro");
  if (windows) {
    writeFileSync(binary, `@echo off\r\necho ${response}\r\nexit /b 0\r\n`);
  } else {
    writeFileSync(binary, `#!/bin/sh\nprintf '%s\\n' '${response}'\n`);
    chmodSync(binary, 0o755);
  }
  return binary;
}

function run(args, overrides = {}) {
  return spawnSync(process.execPath, [installer, ...args], {
    encoding: "utf8",
    timeout: 2500,
    ...overrides,
  });
}

test("legacy setup refuses injected scope before running host commands", () => {
  const root = mkdtempSync(join(tmpdir(), "kicad-legacy-setup-security-"));
  try {
    const payload = process.platform === "win32" ? "project & echo pwned" : "project; echo pwned; #";
    const marker = join(root, "config.json");
    const original = '{"mcpServers":{"other":{"command":"protected"}}}\n';
    writeFileSync(marker, original);
    const output = run(["claude-code", "--scope", payload], { cwd: root });
    assert.notEqual(output.status, 0);
    assert.match(output.stderr, /unsupported scope/i);
    assert.equal(readFileSync(marker, "utf8"), original);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("legacy setup validates all scopes and default agent selection", () => {
  assert.match(run(["not-a-real-agent"]).stderr, /Unknown agent/);
  assert.match(run(["--scope", "user", "not-a-real-agent"]).stderr, /Unknown agent/);
  assert.match(run(["codex", "--scope", "project"]).stderr, /does not support project scope/);
  assert.match(run(["cursor", "--scope", "local"]).stderr, /Unsupported scope/);
  assert.match(run(["--scope", "user"]).stderr, /noninteractive/);
  assert.match(run(["--other", "cursor"]).stderr, /Unknown option/);
  assert.match(run(["cursor", "--scope"]).stderr, /Missing value/);
  assert.match(run(["cursor", "cursor"]).stderr, /Only one agent/);
  assert.equal(run(["--help"]).status, 0);
});

test("nonzero or no confirmed CLI result never becomes success", () => {
  const root = mkdtempSync(join(tmpdir(), "kicad-legacy-setup-failure-"));
  try {
    fakeBinary(root, "Failed to write config: cannot merge existing settings");
    const env = { ...process.env, PATH: `${root}${delimiter}${process.env.PATH ?? ""}` };
    const response = run(["cursor", "--scope", "project"], { cwd: root, env });
    assert.notEqual(response.status, 0);
    assert.match(response.stderr, /did not confirm/);
    assert.doesNotMatch(response.stdout, /configured for/);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("readonly delegation with scope and explicit project directory", () => {
  const root = mkdtempSync(join(tmpdir(), "kicad-legacy-setup-args-"));
  try {
    fakeBinary(root);
    const env = { ...process.env, PATH: `${root}${delimiter}${process.env.PATH ?? ""}` };
    const response = run(["cursor", "--scope", "project", "--project-dir", root], { cwd: root, env });
    assert.equal(response.status, 0, response.stderr);
    assert.match(response.stdout, /cursor \(project scope, readonly\)/);
    assert.doesNotMatch(response.stdout, /Config written to \/safe/);
    assert.equal(existsSync(join(root, ".cursor/mcp.json")), false);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("dry-run is preview-only and not mistaken for write confirmation", () => {
  const root = mkdtempSync(join(tmpdir(), "kicad-legacy-setup-dryrun-"));
  try {
    fakeBinary(root, "Preview config: readonly");
    const env = { ...process.env, PATH: `${root}${delimiter}${process.env.PATH ?? ""}` };
    const response = run(["codex", "--dry-run"], { cwd: root, env });
    assert.equal(response.status, 0, response.stderr);
    assert.match(response.stdout, /Preview only/);
    assert.doesNotMatch(response.stdout, /configured for/);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("legacy installer passes only validated, readonly arguments to Python setup", () => {
  const root = mkdtempSync(join(tmpdir(), "kicad-legacy-setup-capture-"));
  try {
    const marker = join(root, "argv.txt");
    const binary = join(root, process.platform === "win32" ? "kicad-mcp-pro.cmd" : "kicad-mcp-pro");
    if (process.platform === "win32") {
      writeFileSync(binary, '@echo off\r\necho %* > "%CAPTURE_FILE%"\r\necho Config written to safe-test-config\r\n');
    } else {
      writeFileSync(binary, '#!/bin/sh\nprintf "%s\\n" "$@" > "$CAPTURE_FILE"\nprintf "Config written to safe-test-config\\n"\n');
      chmodSync(binary, 0o755);
    }
    const env = { ...process.env, CAPTURE_FILE: marker, PATH: `${root}${delimiter}${process.env.PATH ?? ""}` };
    const response = run(["cursor", "--project-dir", "project with spaces"], { cwd: root, env });
    assert.equal(response.status, 0, response.stderr);
    const forwarded = readFileSync(marker, "utf8");
    assert.match(forwarded, /setup/);
    assert.match(forwarded, /readonly/);
    assert.match(forwarded, /--write/);
    assert.match(forwarded, /project with spaces/);
    assert.doesNotMatch(forwarded, /manufacturing|agent_full/);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});
