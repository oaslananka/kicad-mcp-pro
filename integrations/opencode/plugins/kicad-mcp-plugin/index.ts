/**
 * OpenCode plugin for KiCad MCP integration.
 *
 * Provides:
 * - Config wizard for kicad-mcp-pro setup
 * - kicad:doctor command
 * - kicad:review command
 * - kicad:manufacturing-check command
 * - Toolset switcher
 */

import type { OpenCodePlugin, OpenCodeConfig } from "opencode";

const plugin: OpenCodePlugin = {
  name: "kicad-mcp",
  version: "0.1.0",
  description: "KiCad MCP integration plugin",

  commands: {
    "kicad:doctor": {
      description: "Run KiCad MCP diagnostics",
      execute: async () => {
        const { execSync } = await import("child_process");
        try {
          const output = execSync("kicad-mcp-pro doctor --json", { encoding: "utf-8" });
          return { type: "text", content: output };
        } catch (err: unknown) {
          const message = err instanceof Error ? err.message : String(err);
          return { type: "text", content: `Doctor failed: ${message}` };
        }
      },
    },
    "kicad:review": {
      description: "Run PCB review quality gates",
      execute: async () => {
        return {
          type: "text",
          content:
            "Run these MCP tools in sequence:\n" +
            "1. kicad_get_project_info\n" +
            "2. project_quality_gate\n" +
            "3. run_erc\n" +
            "4. run_drc\n" +
            "5. validate_design",
        };
      },
    },
    "kicad:manufacturing-check": {
      description: "Check manufacturing readiness",
      execute: async () => {
        return {
          type: "text",
          content:
            "Run these checks for manufacturing readiness:\n" +
            "1. project_quality_gate\n" +
            "2. check_design_for_manufacture\n" +
            "3. manufacturing_quality_gate\n" +
            "4. export_gerber (dry-run)\n" +
            "5. export_bom (dry-run)",
        };
      },
    },
  },

  hooks: {
    onConfig: async (config: OpenCodeConfig) => {
      // Auto-detect kicad project and suggest config
      const fs = await import("fs");
      const kicadFiles = fs.readdirSync(".").filter((f: string) => f.endsWith(".kicad_pro"));
      if (kicadFiles.length > 0 && !config.mcp?.kicad) {
        return {
          ...config,
          mcp: {
            ...config.mcp,
            kicad: {
              type: "local",
              command: ["uvx", "kicad-mcp-pro"],
              enabled: true,
              environment: {
                KICAD_MCP_PROJECT_DIR: ".",
                KICAD_MCP_PROFILE: "default",
                KICAD_MCP_OPERATING_MODE: "readonly",
              },
            },
          },
        };
      }
      return config;
    },
  },
};

export default plugin;
