import assert from "node:assert/strict";
import test from "node:test";

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
