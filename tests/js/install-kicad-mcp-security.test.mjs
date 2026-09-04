import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { chmodSync, existsSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { delimiter, join, resolve } from "node:path";
import test from "node:test";

const installer = resolve("integrations/common/install-kicad-mcp.mjs");

function writeFakeExecutable(directory, name, body) {
  const windows = process.platform === "win32";
  const path = join(directory, windows ? `${name}.cmd` : name);
  writeFileSync(path, body, "utf8");
  if (!windows) chmodSync(path, 0o755);
  return path;
}

test("installer rejects shell metacharacters in Claude scope", () => {
  const root = mkdtempSync(join(tmpdir(), "kicad-mcp-installer-security-"));
  const marker = join(root, "injected.txt");
  if (process.platform === "win32") {
    writeFakeExecutable(root, "claude", "@echo off\r\nexit /b 0\r\n");
    writeFakeExecutable(root, "kicad-mcp-pro", "@echo off\r\necho {}\r\nexit /b 0\r\n");
  } else {
    writeFakeExecutable(root, "claude", "#!/bin/sh\nexit 0\n");
    writeFakeExecutable(root, "kicad-mcp-pro", "#!/bin/sh\necho '{}'\nexit 0\n");
  }

  const payload =
    process.platform === "win32"
      ? `project & node -e "require('fs').writeFileSync(process.env.SECURITY_TEST_MARKER,'owned')" & rem`
      : `project; node -e "require('fs').writeFileSync(process.env.SECURITY_TEST_MARKER,'owned')"; #`;
  const result = spawnSync(
    process.execPath,
    [installer, "claude-code", "--scope", payload],
    {
      cwd: root,
      env: {
        ...process.env,
        PATH: `${root}${delimiter}${process.env.PATH ?? ""}`,
        SECURITY_TEST_MARKER: marker,
      },
      encoding: "utf8",
    },
  );

  assert.equal(existsSync(marker), false, "scope payload must never execute in a shell");
  assert.notEqual(result.status, 0, "invalid scope must fail closed");
  assert.match(`${result.stdout}\n${result.stderr}`, /scope.*(invalid|unsupported)|unsupported.*scope/i);
});

function runInstaller(args) {
  return spawnSync(process.execPath, [installer, ...args], {
    encoding: "utf8",
    timeout: 2000,
  });
}

test("installer preserves positional agent parsing with the default scope", () => {
  const result = runInstaller(["not-a-real-agent"]);
  assert.equal(result.status, 1);
  assert.match(result.stderr, /Unknown agent: not-a-real-agent/);
});

test("installer excludes the --scope value from positional agent parsing", () => {
  const result = runInstaller(["--scope", "user", "not-a-real-agent"]);
  assert.equal(result.status, 1);
  assert.match(result.stderr, /Unknown agent: not-a-real-agent/);
});
