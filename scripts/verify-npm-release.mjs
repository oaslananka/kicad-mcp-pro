#!/usr/bin/env node
import { createHash } from "node:crypto";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { basename, join } from "node:path";
import { argv, exit } from "node:process";
import { setTimeout as sleep } from "node:timers/promises";
import { pathToFileURL } from "node:url";

const DEFAULT_REGISTRY_URL = "https://registry.npmjs.org";
const DEFAULT_RETRIES = 6;
const DEFAULT_RETRY_DELAY_MS = 10_000;

function parseArgs(args) {
  const parsed = new Map();
  for (let index = 0; index < args.length; index += 2) {
    parsed.set(args[index], args[index + 1]);
  }
  return parsed;
}

function required(args, key) {
  const value = args.get(key);
  if (!value) throw new Error(`Missing required argument ${key}`);
  return value;
}

export function readChecksums(path) {
  const entries = new Map();
  for (const line of readFileSync(path, "utf8").split(/\r?\n/)) {
    if (!line.trim()) continue;
    const [digest, ...nameParts] = line.trim().split(/\s+/);
    entries.set(nameParts.join(" "), digest);
  }
  return entries;
}

function sha256(buffer) {
  return createHash("sha256").update(buffer).digest("hex");
}

async function fetchJson(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`GET ${url} failed: ${response.status}`);
  return response.json();
}

async function fetchBytes(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`GET ${url} failed: ${response.status}`);
  return Buffer.from(await response.arrayBuffer());
}

export function packageMetadataUrl(
  packageName,
  version,
  registryUrl = DEFAULT_REGISTRY_URL,
) {
  return `${registryUrl.replace(/\/$/, "")}/${encodeURIComponent(packageName)}/${version}`;
}

async function retry(task, attempts, delayMs) {
  let lastError;
  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    try {
      return await task();
    } catch (error) {
      lastError = error;
      if (attempt < attempts) await sleep(delayMs);
    }
  }
  throw lastError;
}

export async function verifyPublishedNpmDigest({
  packageName,
  version,
  checksumsPath,
  outputDir = "release-assets/npm-verify",
  registryUrl = DEFAULT_REGISTRY_URL,
  retries = DEFAULT_RETRIES,
  retryDelayMs = DEFAULT_RETRY_DELAY_MS,
}) {
  const checksums = readChecksums(checksumsPath);
  const metadata = await retry(
    () => fetchJson(packageMetadataUrl(packageName, version, registryUrl)),
    retries,
    retryDelayMs,
  );
  const tarballUrl = metadata?.dist?.tarball;
  if (!tarballUrl)
    throw new Error(
      `npm metadata for ${packageName}@${version} has no tarball URL`,
    );

  const tarball = await fetchBytes(tarballUrl);
  const tarballName = basename(new URL(tarballUrl).pathname);
  let expected = checksums.get(tarballName);
  if (expected === undefined) {
    // Local pack may produce a different basename than the registry
    // (e.g. scoped packages: pack -> oaslananka-kicad-...tgz, registry -> kicad-...tgz).
    // If there is exactly one .tgz entry in checksums, use it as the fallback.
    const tarballEntries = [...checksums.entries()].filter(([name]) =>
      name.endsWith(".tgz"),
    );
    if (tarballEntries.length === 0) {
      throw new Error(`No .tgz entry found in checksums file ${checksumsPath}`);
    }
    if (tarballEntries.length > 1) {
      throw new Error(
        `${tarballName} not found in checksums and multiple .tgz entries exist (` +
          `${tarballEntries.map(([n]) => n).join(", ")}). ` +
          `Cannot unambiguously match. Add an explicit entry for ${tarballName}.`,
      );
    }
    const [entryName, entryDigest] = tarballEntries[0];
    console.log(
      `[warn] tarball basename differs: local="${entryName}" registry="${tarballName}" — matching by digest`,
    );
    expected = entryDigest;
  }
  const actual = sha256(tarball);
  if (expected !== actual) {
    throw new Error(
      `${tarballName} sha256 mismatch: expected ${expected}, got ${actual}`,
    );
  }

  mkdirSync(outputDir, { recursive: true });
  writeFileSync(join(outputDir, tarballName), tarball);
  writeFileSync(
    join(outputDir, "npm-published-digest.json"),
    `${JSON.stringify({ package: packageName, version, tarball: tarballUrl, sha256: actual }, null, 2)}\n`,
  );
}

async function main() {
  const args = parseArgs(argv.slice(2));
  await verifyPublishedNpmDigest({
    packageName: required(args, "--package"),
    version: required(args, "--version"),
    checksumsPath: required(args, "--checksums"),
    outputDir: args.get("--output-dir") ?? "release-assets/npm-verify",
    registryUrl: args.get("--registry") ?? DEFAULT_REGISTRY_URL,
    retries: Number(args.get("--retries") ?? DEFAULT_RETRIES),
    retryDelayMs: Number(
      args.get("--retry-delay-ms") ?? DEFAULT_RETRY_DELAY_MS,
    ),
  });
}

if (argv[1] && import.meta.url === pathToFileURL(argv[1]).href) {
  try {
    await main();
  } catch (error) {
    console.error(error instanceof Error ? error.message : String(error));
    exit(1);
  }
}
