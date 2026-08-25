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
const TRUSTED_REGISTRY_ORIGIN = new URL(DEFAULT_REGISTRY_URL).origin;

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
  const response = await fetch(url, { redirect: "error" });
  if (!response.ok)
    throw new Error(`npm registry metadata request failed: ${response.status}`);
  return response.json();
}

async function fetchBytes(url) {
  const response = await fetch(url, { redirect: "error" });
  if (!response.ok)
    throw new Error(`npm registry tarball request failed: ${response.status}`);
  return Buffer.from(await response.arrayBuffer());
}

function trustedRegistryBase(registryUrl) {
  if (
    registryUrl !== DEFAULT_REGISTRY_URL &&
    registryUrl !== `${DEFAULT_REGISTRY_URL}/`
  ) {
    throw new Error("Release verification requires the trusted npm registry");
  }
  return DEFAULT_REGISTRY_URL;
}

function trustedTarballUrl(rawUrl) {
  let tarball;
  try {
    tarball = new URL(rawUrl);
  } catch {
    throw new Error("npm metadata returned an invalid tarball URL");
  }
  if (
    tarball.protocol !== "https:" ||
    tarball.origin !== TRUSTED_REGISTRY_ORIGIN ||
    tarball.username ||
    tarball.password ||
    tarball.search ||
    tarball.hash ||
    !tarball.pathname.endsWith(".tgz")
  ) {
    throw new Error("npm tarball URL must use the trusted npm registry");
  }
  return new URL(tarball.pathname, `${DEFAULT_REGISTRY_URL}/`).href;
}

export function packageMetadataUrl(
  packageName,
  version,
  registryUrl = DEFAULT_REGISTRY_URL,
) {
  const trustedRegistry = trustedRegistryBase(registryUrl);
  return `${trustedRegistry}/${encodeURIComponent(packageName)}/${encodeURIComponent(version)}`;
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
  const rawTarballUrl = metadata?.dist?.tarball;
  if (!rawTarballUrl) throw new Error("npm metadata has no tarball URL");

  const tarballUrl = trustedTarballUrl(rawTarballUrl);
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
      throw new Error("No .tgz entry found in checksums file");
    }
    if (tarballEntries.length > 1) {
      throw new Error(
        "Published tarball did not match the checksums file and multiple .tgz entries exist",
      );
    }
    const [, entryDigest] = tarballEntries[0];
    console.log(
      "[warn] tarball basename differs; matching the sole .tgz entry by digest",
    );
    expected = entryDigest;
  }
  const actual = sha256(tarball);
  if (expected !== actual) {
    throw new Error("Published npm tarball sha256 mismatch");
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
  main().catch((error) => {
    console.error(error instanceof Error ? error.message : String(error));
    exit(1);
  });
}
