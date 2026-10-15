import assert from "node:assert/strict";
import test from "node:test";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

import { resolveGhExecutable } from "../../scripts/classify-gh-failure.mjs";

test("GitHub CLI resolution uses fixed absolute system paths", () => {
  const linuxSeen = [];
  assert.equal(
    resolveGhExecutable("linux", (path) => {
      linuxSeen.push(path);
      return path === "/usr/bin/gh";
    }),
    "/usr/bin/gh",
  );
  assert.deepEqual(linuxSeen, ["/usr/bin/gh"]);

  assert.equal(
    resolveGhExecutable("darwin", (path) => path === "/opt/homebrew/bin/gh"),
    "/opt/homebrew/bin/gh",
  );

  assert.equal(
    resolveGhExecutable(
      "win32",
      (path) => path === "C:\\Program Files\\GitHub CLI\\gh.exe",
    ),
    "C:\\Program Files\\GitHub CLI\\gh.exe",
  );
});

test("GitHub CLI resolution fails closed instead of searching PATH", () => {
  const seen = [];
  assert.throws(
    () =>
      resolveGhExecutable("linux", (path) => {
        seen.push(path);
        return false;
      }),
    /trusted system locations/i,
  );
  assert.deepEqual(seen, ["/usr/bin/gh", "/usr/local/bin/gh"]);
});

test("release-tag rejection is classified on long logs without regex backtracking", () => {
  const script = fileURLToPath(new URL("../../scripts/classify-gh-failure.mjs", import.meta.url));
  const input = "refs/tags/v" + "a".repeat(15_000) + " was rejected";
  const result = spawnSync(process.execPath, [script, "--json"], {
    input,
    encoding: "utf8",
    timeout: 10_000,
  });
  assert.equal(result.status, 0, result.stderr);
  assert.equal(JSON.parse(result.stdout).classification, "release-tag-collision");
});
