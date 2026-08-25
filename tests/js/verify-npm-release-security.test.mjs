import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import {
  packageMetadataUrl,
  packageTarballUrl,
  verifyPublishedNpmDigest,
} from "../../scripts/verify-npm-release.mjs";

const PACKAGE = "kicad-mcp-pro";
const VERSION = "3.33.0";

function temporaryDirectory() {
  return mkdtempSync(join(tmpdir(), "kicad-npm-verifier-"));
}

test("tarball URL is derived from canonical package identity", () => {
  assert.equal(
    packageTarballUrl("kicad-mcp-pro", "3.32.0"),
    "https://registry.npmjs.org/kicad-mcp-pro/-/kicad-mcp-pro-3.32.0.tgz",
  );
  assert.equal(
    packageTarballUrl("@oaslananka/kicad-protocol-schemas", "1.4.1"),
    "https://registry.npmjs.org/%40oaslananka/kicad-protocol-schemas/-/kicad-protocol-schemas-1.4.1.tgz",
  );
});

test("package metadata rejects an untrusted registry origin", () => {
  assert.throws(
    () => packageMetadataUrl(PACKAGE, VERSION, "https://attacker.invalid"),
    /trusted npm registry/i,
  );
});

test("published digest verification rejects a cross-origin tarball before fetching it", async () => {
  const directory = temporaryDirectory();
  const checksumsPath = join(directory, "SHA256SUMS.txt");
  writeFileSync(checksumsPath, `${"0".repeat(64)}  package.tgz\n`);

  const requested = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (input) => {
    const url = String(input);
    requested.push(url);
    if (requested.length === 1) {
      return {
        ok: true,
        status: 200,
        json: async () => ({
          dist: { tarball: "https://attacker.invalid/package.tgz" },
        }),
      };
    }
    throw new Error(`unexpected cross-origin fetch: ${url}`);
  };

  try {
    await assert.rejects(
      verifyPublishedNpmDigest({
        packageName: PACKAGE,
        version: VERSION,
        checksumsPath,
        outputDir: join(directory, "out"),
        retries: 1,
        retryDelayMs: 0,
      }),
      /trusted npm registry/i,
    );
    assert.equal(requested.length, 1);
  } finally {
    globalThis.fetch = originalFetch;
    rmSync(directory, { recursive: true, force: true });
  }
});

test("basename fallback warning does not log registry-controlled names", async () => {
  const directory = temporaryDirectory();
  const checksumsPath = join(directory, "SHA256SUMS.txt");
  const payload = new TextEncoder().encode("published tarball bytes");
  const digest = createHash("sha256").update(payload).digest("hex");
  writeFileSync(checksumsPath, `${digest}  local-name.tgz\n`);

  const originalFetch = globalThis.fetch;
  const originalLog = console.log;
  const logs = [];
  let requestNumber = 0;
  globalThis.fetch = async () => {
    requestNumber += 1;
    if (requestNumber === 1) {
      return {
        ok: true,
        status: 200,
        json: async () => ({
          dist: {
            tarball:
              "https://registry.npmjs.org/kicad-mcp-pro/-/registry-name.tgz",
          },
        }),
      };
    }
    return {
      ok: true,
      status: 200,
      arrayBuffer: async () => payload.buffer,
    };
  };
  console.log = (...args) => logs.push(args.join(" "));

  try {
    await verifyPublishedNpmDigest({
      packageName: PACKAGE,
      version: VERSION,
      checksumsPath,
      outputDir: join(directory, "out"),
      retries: 1,
      retryDelayMs: 0,
    });
    assert.equal(logs.length, 1);
    assert.match(logs[0], /basename differs/i);
    assert.doesNotMatch(logs[0], /local-name|registry-name/i);
  } finally {
    globalThis.fetch = originalFetch;
    console.log = originalLog;
    rmSync(directory, { recursive: true, force: true });
  }
});
