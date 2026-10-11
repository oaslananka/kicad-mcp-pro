#!/usr/bin/env node
/**
 * Legacy Node.js setup entry point; Python CLI is the single config writer.
 *
 *   node integrations/common/install-kicad-mcp.mjs cursor --scope project
 *   node integrations/common/install-kicad-mcp.mjs codex --scope user
 *   node integrations/common/install-kicad-mcp.mjs cursor --dry-run
 *
 * No host config is copied/overwritten here. The Python setup CLI performs
 * validated merge, uniquely named backups and atomic replacement.
 */

import { spawnSync } from "node:child_process";
import { createInterface } from "node:readline";

const SCOPES = Object.freeze({
  "claude-code": ["project", "user"],
  codex: ["user"],
  gemini: ["user"],
  opencode: ["project", "user"],
  "claude-desktop": ["user"],
  cursor: ["project", "user"],
  vscode: ["project"],
  antigravity: ["user"],
});

function usage() {
  console.log(`KiCad MCP Pro legacy setup bridge

Usage: node install-kicad-mcp.mjs [agent] [--scope project|user] [--project-dir DIR] [--dry-run]

Agents: ${Object.keys(SCOPES).join(", ")}

Uses kicad-mcp-pro setup, preserving unrelated configuration with validated
merge, timestamped backups, and atomic writes. Installs read-only access only.
Install the Python CLI first: uv tool install kicad-mcp-pro
For an interactive setup use: kicad-mcp-pro setup wizard
`);
}

function parseArgs(args) {
  let agent = null;
  let scope = null;
  let projectDir = null;
  let dryRun = false;
  for (let i = 0; i < args.length; i += 1) {
    const arg = args[i];
    if (arg === "--help" || arg === "-h") return { help: true };
    if (arg === "--dry-run") {
      dryRun = true;
      continue;
    }
    if (arg === "--scope" || arg === "--project-dir") {
      const value = args[++i];
      if (!value || value.startsWith("--")) throw new Error(`Missing value for ${arg}`);
      if (arg === "--scope") {
        if (scope !== null) throw new Error("Duplicate --scope");
        scope = value;
      } else {
        if (projectDir !== null) throw new Error("Duplicate --project-dir");
        projectDir = value;
      }
      continue;
    }
    if (arg.startsWith("-")) throw new Error(`Unknown option: ${arg}`);
    if (agent !== null) throw new Error("Only one agent may be configured at a time");
    agent = arg;
  }
  if (scope !== null && !["project", "user"].includes(scope)) {
    throw new Error(`Unsupported scope: ${scope}. Use project or user (local is not a valid Python setup scope)`);
  }
  if (agent !== null && !Object.hasOwn(SCOPES, agent)) {
    throw new Error(`Unknown agent: ${agent}. Supported: ${Object.keys(SCOPES).join(", ")}`);
  }
  return { agent, scope, projectDir, dryRun };
}

async function promptAgent() {
  if (!process.stdin.isTTY) throw new Error("Specify an agent in noninteractive mode");
  const rl = createInterface({ input: process.stdin, output: process.stdout });
  try {
    return (await new Promise((resolve) => rl.question("Which agent? ", resolve))).trim();
  } finally {
    rl.close();
  }
}

async function main() {
  let opts;
  try {
    opts = parseArgs(process.argv.slice(2));
    if (opts.help) { usage(); return; }
    const agent = opts.agent ?? await promptAgent();
    if (!Object.hasOwn(SCOPES, agent)) throw new Error(`Unknown agent: ${agent}`);
    const allowed = SCOPES[agent];
    const scope = opts.scope ?? (allowed.includes("project") ? "project" : "user");
    if (!allowed.includes(scope)) {
      throw new Error(`Agent ${agent} does not support ${scope} scope; supported: ${allowed.join(", ")}`);
    }
    const argv = ["setup", agent, "--scope", scope, "--mode", "readonly"];
    if (opts.projectDir !== null) argv.push("--project-dir", opts.projectDir);
    if (!opts.dryRun) argv.push("--write");
    const result = spawnSync("kicad-mcp-pro", argv, {
      encoding: "utf8",
      shell: false,
      timeout: 45_000,
      maxBuffer: 1024 * 1024,
    });
    if (result.error || result.signal || result.status !== 0) {
      throw new Error("Python setup CLI failed. Check kicad-mcp-pro setup --help and verify its installation.");
    }
    // Some older Python setup versions return exit 0 even for write errors.
    // Never report success without the positive, owned config write result.
    if (!opts.dryRun && !result.stdout?.includes("Config written to ")) {
      throw new Error("Python setup did not confirm a successful validated config write");
    }
    if (opts.dryRun) {
      console.log(result.stdout);
      console.log("Preview only: no configuration was written.");
    } else {
      console.log(`KiCad MCP configured for ${agent} (${scope} scope, readonly).`);
      console.log("Unrelated client settings were preserved by the Python setup writer.");
      console.log("Run 'kicad-mcp-pro doctor' and verify a read-only tool in the actual agent.");
    }
  } catch (error) {
    console.error(`Setup refused: ${error.message}`);
    process.exitCode = 1;
  }
}

await main();
