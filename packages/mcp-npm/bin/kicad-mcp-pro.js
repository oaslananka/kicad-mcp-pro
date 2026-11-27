#!/usr/bin/env node
"use strict";

const fs = require("node:fs");
const path = require("node:path");
const { spawn } = require("node:child_process");
const pkg = require("../package.json");

function executableNames() {
  return process.platform === "win32" ? ["uvx.exe"] : ["uvx"];
}

function findOnPath(commandNames) {
  const rawPath = process.env.PATH || "";
  const entries = rawPath.split(path.delimiter).filter(Boolean);
  for (const entry of entries) {
    for (const commandName of commandNames) {
      const candidate = path.join(entry, commandName);
      if (fs.statSync(candidate, { throwIfNoEntry: false })?.isFile()) {
        return candidate;
      }
    }
  }
  return null;
}

const uvx = findOnPath(executableNames());
if (!uvx) {
  console.error(
    [
      "uvx was not found on PATH.",
      "Install uv from https://docs.astral.sh/uv/getting-started/installation/ and retry.",
      "This npm wrapper does not install the Python package during npm install.",
    ].join("\n"),
  );
  process.exit(127);
}

const pythonPackageVersion = process.env.KICAD_MCP_PRO_PYPI_VERSION || pkg.version;
const pythonPackage = `kicad-mcp-pro@${pythonPackageVersion}`;
const child = spawn(uvx, [pythonPackage, ...process.argv.slice(2)], {
  stdio: "inherit",
  windowsHide: true,
});

child.on("error", (error) => {
  console.error(`Failed to execute uvx: ${error.message}`);
  process.exit(1);
});

child.on("exit", (code, signal) => {
  if (signal) {
    process.kill(process.pid, signal);
    return;
  }
  if (code !== 0) {
    console.error(
      [
        `${pythonPackage} exited with code ${code}.`,
        "Publish the matching Python package before publishing this npm wrapper,",
        "or set KICAD_MCP_PRO_PYPI_VERSION to an already-published compatible version.",
      ].join("\n"),
    );
  }
  process.exit(code === null ? 1 : code);
});
