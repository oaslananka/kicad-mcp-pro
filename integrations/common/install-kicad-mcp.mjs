#!/usr/bin/env node
/**
 * Universal KiCad MCP installer for any agent/IDE.
 *
 * Usage:
 *   node install-kicad-mcp.mjs                  # interactive wizard
 *   node install-kicad-mcp.mjs claude-code      # direct install
 *   node install-kicad-mcp.mjs --scope user claude-code
 */

import { execFileSync } from "child_process";
import { existsSync, mkdirSync, readFileSync, writeFileSync, copyFileSync } from "fs";
import { homedir, platform } from "os";
import { join, resolve } from "path";
import { createInterface } from "readline";

const INTEGRATIONS_DIR = new URL(".", import.meta.url).pathname;

const AGENTS = {
  "claude-code": {
    install: (scope) =>
      execFileSync(
        "claude",
        [
          "mcp",
          "add",
          "--transport",
          "stdio",
          "--scope",
          scope,
          "kicad",
          "--",
          "uvx",
          "kicad-mcp-pro",
        ],
        { stdio: "inherit" },
      ),
    configPath: (scope) =>
      scope === "project"
        ? join(process.cwd(), ".mcp.json")
        : join(homedir(), ".claude.json"),
    example: join(INTEGRATIONS_DIR, "..", "claude-code", ".mcp.json.example"),
  },
  codex: {
    configPath: (scope) =>
      scope === "project"
        ? join(process.cwd(), ".codex", "config.toml")
        : join(homedir(), ".codex", "config.toml"),
    example: join(INTEGRATIONS_DIR, "..", "codex", "config.toml.example"),
  },
  gemini: {
    configPath: () => join(homedir(), ".gemini", "settings.json"),
    example: join(INTEGRATIONS_DIR, "..", "gemini-cli", "settings.example.json"),
  },
  opencode: {
    configPath: () => join(process.cwd(), "opencode.json"),
    example: join(INTEGRATIONS_DIR, "..", "opencode", "opencode.example.json"),
  },
  "claude-desktop": {
    configPath: () => {
      const paths = {
        win32: join(process.env.APPDATA || "", "Claude", "claude_desktop_config.json"),
        darwin: join(homedir(), "Library", "Application Support", "Claude", "claude_desktop_config.json"),
        linux: join(homedir(), ".config", "Claude", "claude_desktop_config.json"),
      };
      return paths[platform()] || paths.linux;
    },
    example: join(INTEGRATIONS_DIR, "..", "claude-desktop", "claude_desktop_config.example.json"),
  },
  cursor: {
    configPath: () => join(process.cwd(), ".cursor", "mcp.json"),
    example: join(INTEGRATIONS_DIR, "..", "cursor", "mcp.example.json"),
  },
  vscode: {
    configPath: () => join(process.cwd(), ".vscode", "mcp.json"),
    example: join(INTEGRATIONS_DIR, "..", "vscode", "mcp.example.json"),
  },
  antigravity: {
    configPath: () => join(homedir(), ".gemini", "config", "mcp_config.json"),
    example: join(INTEGRATIONS_DIR, "..", "antigravity", "mcp_config.example.json"),
  },
};

async function prompt(question) {
  const rl = createInterface({ input: process.stdin, output: process.stdout });
  return new Promise((resolve) => rl.question(question, (a) => { rl.close(); resolve(a); }));
}

async function main() {
  const args = process.argv.slice(2);
  const scopeIndex = args.indexOf("--scope");
  const scopeArg = scopeIndex >= 0 ? args[scopeIndex + 1] : "project";
  const supportedScopes = new Set(["local", "project", "user"]);
  if (!supportedScopes.has(scopeArg)) {
    console.error(`Unsupported scope: ${scopeArg ?? "<missing>"}. Supported: local, project, user`);
    process.exit(2);
  }
  const agentArg = args.find(
    (arg, index) =>
      !arg.startsWith("--") && (scopeIndex < 0 || index !== scopeIndex + 1),
  );

  const agentName = agentArg || await prompt("Which agent? (claude-code, codex, gemini, opencode, cursor, vscode, claude-desktop, antigravity): ");
  const agent = AGENTS[agentName.trim().toLowerCase()];
  if (!agent) {
    console.error(`Unknown agent: ${agentName}`);
    console.error(`Supported: ${Object.keys(AGENTS).join(", ")}`);
    process.exit(1);
  }

  const configPath = agent.configPath(scopeArg);
  const configDir = resolve(configPath, "..");

  if (!existsSync(configDir)) {
    mkdirSync(configDir, { recursive: true });
  }

  if (agent.install) {
    try {
      agent.install(scopeArg);
      console.log(`✓ KiCad MCP configured for ${agentName} (${scopeArg} scope)`);
    } catch (err) {
      console.error(`✗ Failed: ${err.message}`);
      process.exit(1);
    }
  } else if (agent.example) {
    if (existsSync(configPath)) {
      const backup = configPath + ".bak";
      copyFileSync(configPath, backup);
      console.log(`   Backed up existing config to ${backup}`);
    }
    copyFileSync(agent.example, configPath);
    console.log(`✓ Config written to ${configPath}`);
    console.log("  Edit KICAD_MCP_PROJECT_DIR to match your KiCad project.");
  }

  // Run doctor after install
  try {
    const doctor = execFileSync("kicad-mcp-pro", ["doctor", "--json"], {
      encoding: "utf-8",
      timeout: 15000,
    });
    const report = JSON.parse(doctor);
    console.log(`✓ Doctor: status=${report.status}, tools=${report.tools?.tool_count ?? "?"}`);
  } catch {
    console.log("  Run 'kicad-mcp-pro doctor' after setup to verify.");
  }
}

main();
