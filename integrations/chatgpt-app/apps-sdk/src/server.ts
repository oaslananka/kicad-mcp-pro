/**
 * KiCad MCP ChatGPT App — Remote MCP Server
 *
 * Provides KiCad project analysis tools for ChatGPT GPTs.
 * Runs in two modes:
 *   1. **Proxied** — Spawns `kicad-mcp-pro` as a subprocess and
 *      forwards tool calls via stdio MCP (full local toolset available).
 *   2. **Standalone** — Falls back to heuristic / static analysis when
 *      the Python backend is not installed (useful for cloud hosting).
 *
 * Also serves 3 UI widgets:
 *   - /widgets/dashboard       — Board overview, layers, component count
 *   - /widgets/project-review  — DRC/ERC issues grouped by severity
 *   - /widgets/manufacturing   — Step-by-step release checklist
 */

import express, { type Request, type Response } from "express";
import rateLimit from "express-rate-limit";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/streamableHttp.js";
import { z } from "zod";
import { existsSync, lstatSync, readFileSync, realpathSync } from "node:fs";
import { readdir } from "node:fs/promises";
import { isAbsolute, join, normalize, relative, resolve } from "node:path";
import { spawn } from "node:child_process";
import { tmpdir } from "node:os";

// ---------------------------------------------------------------------------
// Security — safe workspace resolution and rate limiting
// ---------------------------------------------------------------------------

const ALLOWED_EXTENSIONS = new Set([
  ".kicad_proj", ".kicad_pcb", ".kicad_sch",
  ".zip", ".gz", ".tar",
  ".json",
]);

const RATE_LIMIT_WINDOW_MS = 60_000;
const RATE_LIMIT_MAX_REQUESTS = 120;

/**
 * Optional, deployment-specific roots for uploaded/cached projects.
 *
 * ChatGPT Apps should normally hand this server temp/extracted directories.
 * Production deployments that persist uploads elsewhere can set a platform
 * path-list here (":" on POSIX, ";" on Windows).  The OS temp directory is
 * always allowed so test/upload sandboxes keep working without extra config.
 */
const CONFIGURED_UPLOAD_ROOTS = (process.env.KICAD_MCP_UPLOAD_ROOTS || "")
  .split(process.platform === "win32" ? ";" : ":")
  .map((entry) => entry.trim())
  .filter(Boolean);

type SafeFsPath = string & { readonly __safeFsPath: unique symbol };

function asSafeFsPath(pathValue: string): SafeFsPath {
  return pathValue as SafeFsPath;
}

function canonicalizePath(pathValue: string): string {
  return normalize(resolve(pathValue));
}

function canonicalizeExistingPath(pathValue: string): string {
  return canonicalizePath(realpathSync(pathValue));
}

function allowedWorkspaceRoots(): string[] {
  return [tmpdir(), ...CONFIGURED_UPLOAD_ROOTS]
    .map(canonicalizePath)
    .filter((root) => existsSync(root))
    .map(canonicalizeExistingPath);
}

function isWithinRoot(root: string, candidate: string): boolean {
  const rel = relative(root, candidate);
  return rel === "" || (rel !== "" && !rel.startsWith("..") && !isAbsolute(rel));
}

function assertAllowedRealPath(candidate: string, label: string): SafeFsPath {
  const canonical = canonicalizeExistingPath(candidate);
  const roots = allowedWorkspaceRoots();
  if (roots.some((root) => isWithinRoot(root, canonical))) {
    return asSafeFsPath(canonical);
  }
  throw new Error(`${label}: path is outside allowed upload roots`);
}

function safeReadUtf8(pathValue: SafeFsPath): string {
  // The SafeFsPath brand is only created after realpath and upload-root checks.
  return readFileSync(pathValue, "utf-8"); // lgtm[js/path-injection]
}

async function safeReadDir(pathValue: SafeFsPath) {
  // The SafeFsPath brand is only created after realpath and upload-root checks.
  return readdir(pathValue, { withFileTypes: true }); // lgtm[js/path-injection]
}

async function safeReadDirNames(pathValue: SafeFsPath): Promise<string[]> {
  // The SafeFsPath brand is only created after realpath and upload-root checks.
  return readdir(pathValue); // lgtm[js/path-injection]
}

function safeExists(pathValue: SafeFsPath): boolean {
  // The SafeFsPath brand is only created after realpath and upload-root checks.
  return existsSync(pathValue); // lgtm[js/path-injection]
}

function assertPathSegmentSafe(userPath: string, label: string): void {
  if (typeof userPath !== "string" || userPath.length === 0) {
    throw new Error(`${label}: path must be a non-empty string`);
  }
  if (userPath.includes("\u0000")) {
    throw new Error(`${label}: path contains null byte`);
  }
  if (/[%]2[ef]/i.test(userPath) || /[%]5c/i.test(userPath)) {
    throw new Error(`${label}: path contains URL-encoded traversal`);
  }
  if (userPath.replace(/\\/g, "/").split("/").includes("..")) {
    throw new Error(`${label}: directory traversal detected`);
  }
}

/**
 * Resolve a user-supplied project directory into an allowlisted workspace path.
 * All file-system operations must use this returned canonical path, not the raw
 * request parameter.  This keeps CodeQL-visible file access anchored under
 * explicit upload roots and blocks arbitrary absolute path reads.
 */
function resolveSafeWorkspaceDirectory(userPath: string, label: string): SafeFsPath {
  assertPathSegmentSafe(userPath, label);

  const roots = allowedWorkspaceRoots();
  if (roots.length === 0) {
    throw new Error(`${label}: no allowed upload roots are available`);
  }

  const candidate = isAbsolute(userPath)
    ? canonicalizePath(userPath)
    : canonicalizePath(join(roots[0], userPath));
  const safeCandidate = assertAllowedRealPath(candidate, label);
  if (!lstatSync(safeCandidate).isDirectory()) { // lgtm[js/path-injection]
    throw new Error(`${label}: path must be a directory`);
  }
  return safeCandidate;
}

function resolveSafeChild(parent: SafeFsPath, childName: string, label: string): SafeFsPath {
  assertPathSegmentSafe(childName, label);
  const candidate = canonicalizePath(join(parent, childName));
  if (!isWithinRoot(parent, candidate)) {
    throw new Error(`${label}: child path escapes parent directory`);
  }
  return assertAllowedRealPath(candidate, label);
}

function resolveProjectSibling(projectPath: SafeFsPath, extension: string): SafeFsPath {
  if (!ALLOWED_EXTENSIONS.has(extension)) {
    throw new Error(`Unsupported KiCad project extension: ${extension}`);
  }
  const projectDir = canonicalizePath(resolve(projectPath, ".."));
  const sibling = canonicalizePath(projectPath.replace(/\.kicad_proj$/, extension));
  if (!isWithinRoot(projectDir, sibling)) {
    throw new Error("Project sibling path escapes project directory");
  }
  if (!existsSync(sibling)) { // lgtm[js/path-injection]
    return asSafeFsPath(sibling);
  }
  return assertAllowedRealPath(sibling, `project sibling ${extension}`);
}

const analyzeRateLimiter = rateLimit({
  windowMs: RATE_LIMIT_WINDOW_MS,
  limit: RATE_LIMIT_MAX_REQUESTS,
  standardHeaders: "draft-7",
  legacyHeaders: false,
  message: { error: "Too many requests. Please slow down." },
});

// ---------------------------------------------------------------------------
// Configuration
// ---------------------------------------------------------------------------

const PORT = parseInt(process.env.PORT || "8765", 10);
const HOST = process.env.HOST || "0.0.0.0";
const KICAD_MCP_CMD = process.env.KICAD_MCP_CMD || "kicad-mcp-pro";
const STATIC_DIR = resolve(import.meta.dirname, "..", "public");
const APP_PACKAGE = JSON.parse(
  readFileSync(resolve(import.meta.dirname, "..", "package.json"), "utf8"),
) as { version: string };
const APP_NAME = "KiCad MCP Pro";
const APP_VERSION = APP_PACKAGE.version;
const LOCAL_READ_ONLY_ANNOTATIONS = {
  readOnlyHint: true,
  destructiveHint: false,
  idempotentHint: true,
  openWorldHint: false,
} as const;
const OPEN_WORLD_READ_ONLY_ANNOTATIONS = {
  ...LOCAL_READ_ONLY_ANNOTATIONS,
  openWorldHint: true,
} as const;

// ---------------------------------------------------------------------------
// Helpers — KiCad project parsing
// ---------------------------------------------------------------------------

interface KiCadProject {
  name: string;
  path: SafeFsPath;
  boardPath: SafeFsPath | null;
  schematicPath: SafeFsPath | null;
  metadata: Record<string, unknown>;
}

interface KiCadBoard {
  layers: number;
  boardThickness: number | null;
  copperLayers: number;
  componentCount: number;
  trackCount: number;
  viaCount: number;
}

interface KiCadSchematic {
  componentCount: number;
  netCount: number;
  sheetCount: number;
}

function parseKiCadProj(path: SafeFsPath): Record<string, unknown> {
  try {
    return JSON.parse(safeReadUtf8(path));
  } catch {
    return {};
  }
}

function parseKiCadPcbLayers(pcb: Record<string, unknown>, fallback = 4): number {
  const layers = (pcb as Record<string, unknown>).layers;
  if (Array.isArray(layers)) return layers.length;
  return fallback;
}

function countBoardComponents(pcb: Record<string, unknown>): number {
  const footprint = (pcb as Record<string, unknown>).footprint;
  if (Array.isArray(footprint)) return footprint.length;
  return 0;
}

function countBoardTracks(pcb: Record<string, unknown>): number {
  const segment = (pcb as Record<string, unknown>).segment;
  if (Array.isArray(segment)) return segment.length;
  return 0;
}

function countBoardVias(pcb: Record<string, unknown>): number {
  const via = (pcb as Record<string, unknown>).via;
  if (Array.isArray(via)) return via.length;
  return 0;
}

async function extractProject(dir: SafeFsPath): Promise<SafeFsPath> {
  const entries = await safeReadDir(dir);
  const kicadProj = entries.find(
    (e) => e.isFile() && e.name.endsWith(".kicad_proj"),
  );
  if (!kicadProj) {
    // Look for any project file inside a subdirectory
    for (const entry of entries) {
      if (entry.isDirectory()) {
        const subdir = resolveSafeChild(dir, entry.name, "nested project directory");
        const sub = await safeReadDirNames(subdir);
        const nested = sub.find((f) => f.endsWith(".kicad_proj"));
        if (nested) return resolveSafeChild(subdir, nested, "nested project file");
      }
    }
    throw new Error("No .kicad_proj file found in archive");
  }
  return resolveSafeChild(dir, kicadProj.name, "project file");
}

function getBoardThickness(pcb: Record<string, unknown>): number | null {
  const setup = pcb.setup as Record<string, unknown> | undefined;
  const thickness = setup?.board_thickness;
  return typeof thickness === "number" ? thickness : null;
}

function analyzePcbFile(pcbPath: SafeFsPath): KiCadBoard {
  try {
    const raw = safeReadUtf8(pcbPath);
    const pcb = JSON.parse(raw) as Record<string, unknown>;
    return {
      layers: parseKiCadPcbLayers(pcb),
      boardThickness: getBoardThickness(pcb),
      copperLayers: parseKiCadPcbLayers(pcb),
      componentCount: countBoardComponents(pcb),
      trackCount: countBoardTracks(pcb),
      viaCount: countBoardVias(pcb),
    };
  } catch {
    return { layers: 0, boardThickness: null, copperLayers: 0, componentCount: 0, trackCount: 0, viaCount: 0 };
  }
}

// ---------------------------------------------------------------------------
// In-memory project store
// ---------------------------------------------------------------------------

const projects = new Map<string, KiCadProject>();

// ---------------------------------------------------------------------------
// Helpers — DRC / ERC report interpretation
// ---------------------------------------------------------------------------

interface ReportSummary {
  errors: number;
  warnings: number;
  issues: Array<{ severity: string; rule: string; description: string }>;
}

function analyzeDrcReport(text: string): ReportSummary {
  const lines = text.split("\n");
  const issues: Array<{ severity: string; rule: string; description: string }> = [];
  let errors = 0;
  let warnings = 0;
  for (const line of lines) {
    const trimmed = line.trim();
    if (/^error|^[✗❌]|violations? found/i.test(trimmed)) errors++;
    else if (/^warn|^⚠|warning/i.test(trimmed)) warnings++;
    // Try to parse structured DRC output
    const ruleMatch = trimmed.match(/\(([\w-]+)\)\s*:\s*(.+)/);
    if (ruleMatch) {
      issues.push({ severity: "error", rule: ruleMatch[1], description: ruleMatch[2] });
    }
  }
  // Fallback: count occurrences
  errors = Math.max(errors, (text.match(/\berror\b/gi) || []).length);
  warnings = Math.max(warnings, (text.match(/\bwarning\b/gi) || []).length);
  return { errors, warnings, issues };
}

function analyzeErcReport(text: string): ReportSummary {
  const issues: Array<{ severity: string; rule: string; description: string }> = [];
  const lines = text.split("\n");
  let errors = 0;
  let warnings = 0;
  for (const line of lines) {
    const trimmed = line.trim();
    if (/^error|^[✗❌]|conflict/i.test(trimmed)) errors++;
    else if (/^warn|^⚠|unconnected|not connected/i.test(trimmed)) warnings++;
    const ruleMatch = trimmed.match(/\(([\w-]+)\)\s*:\s*(.+)/);
    if (ruleMatch) {
      issues.push({ severity: "error", rule: ruleMatch[1], description: ruleMatch[2] });
    }
  }
  errors = Math.max(errors, (text.match(/\berror\b/gi) || []).length);
  warnings = Math.max(warnings, (text.match(/\bwarning\b/gi) || []).length);
  return { errors, warnings, issues };
}

// ---------------------------------------------------------------------------
// Manufacturing readiness checklist
// ---------------------------------------------------------------------------

interface ManufacturingChecklist {
  overall: "ready" | "not_ready";
  checks: Array<{ name: string; passed: boolean; detail: string }>;
}

function generateReadinessChecklist(drcErrors: number, ercErrors: number, hasBom: boolean, hasGerbers: boolean): ManufacturingChecklist {
  const checks: Array<{ name: string; passed: boolean; detail: string }> = [
    { name: "DRC Clean", passed: drcErrors === 0, detail: drcErrors > 0 ? `${drcErrors} DRC error(s) remaining` : "No DRC errors" },
    { name: "ERC Clean", passed: ercErrors === 0, detail: ercErrors > 0 ? `${ercErrors} ERC error(s) remaining` : "No ERC errors" },
    { name: "BOM Generated", passed: hasBom, detail: hasBom ? "BOM available" : "BOM not generated" },
    { name: "Gerbers Exported", passed: hasGerbers, detail: hasGerbers ? "Gerber files available" : "Gerber files not exported" },
  ];
  const overall = checks.every((c) => c.passed) ? "ready" : "not_ready";
  return { overall, checks };
}

// ---------------------------------------------------------------------------
// Subprocess bridge to kicad-mcp-pro
// ---------------------------------------------------------------------------

function runKicadMcp(method: string, args: Record<string, unknown>): Promise<string> {
  return new Promise((resolve, reject) => {
    const proc = spawn("uvx", ["kicad-mcp-pro", method, "--json"], {
      stdio: ["pipe", "pipe", "pipe"],
      timeout: 30_000,
    });
    let stdout = "";
    let stderr = "";
    proc.stdout.on("data", (chunk: Buffer) => { stdout += chunk.toString(); });
    proc.stderr.on("data", (chunk: Buffer) => { stderr += chunk.toString(); });
    proc.on("close", (code) => {
      if (code === 0 && stdout) resolve(stdout);
      else reject(new Error(stderr || `Process exited with code ${code}`));
    });
    proc.on("error", (err) => reject(err));
    proc.stdin.write(JSON.stringify({ jsonrpc: "2.0", method, params: args, id: 1 }) + "\n");
    proc.stdin.end();
  });
}

// ---------------------------------------------------------------------------
// Express App + MCP Server
// ---------------------------------------------------------------------------

const app = express();
app.use(express.json({ limit: "50mb" }));

// Serve HTML widgets
app.use("/widgets", express.static(STATIC_DIR));

// Rewrite / to redirect to dashboard
app.get("/", (_req: Request, res: Response) => {
  res.redirect("/widgets/kicad-dashboard.html");
});

// Project upload endpoint (rate-limited, path-safety validated)
app.post("/api/analyze", analyzeRateLimiter, async (req: Request, res: Response) => {
  try {
    const { projectDir } = req.body as { projectDir?: string };
    if (!projectDir) {
      return res.status(400).json({ error: "projectDir is required" });
    }
    // Resolve the user-supplied path before any file operations.
    const safeProjectDir = resolveSafeWorkspaceDirectory(projectDir, "projectDir");
    const projPath = await extractProject(safeProjectDir);
    const name = projPath.replace(/\.kicad_proj$/, "").split(/[/\\]/).pop() || "unknown";
    const boardPath = resolveProjectSibling(projPath, ".kicad_pcb");
    const schematicPath = resolveProjectSibling(projPath, ".kicad_sch");
    const metadata = parseKiCadProj(projPath);
    const project: KiCadProject = {
      name,
      path: projPath,
      boardPath: safeExists(boardPath) ? boardPath : null,
      schematicPath: safeExists(schematicPath) ? schematicPath : null,
      metadata,
    };
    projects.set(name, project);
    return res.json(project);
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    return res.status(400).json({ error: message });
  }
});

// MCP Server
function createMcpServer(): McpServer {
  const mcp = new McpServer({
    name: APP_NAME,
    version: APP_VERSION,
  });

  mcp.registerTool(
    "search_kicad_knowledge",
    {
      annotations: OPEN_WORLD_READ_ONLY_ANNOTATIONS,
      description: "Search KiCad documentation and knowledge base for PCB design topics.",
      inputSchema: {
        query: z.string().describe("Search query (e.g. 'footprint editor', 'differential pair routing')"),
        maxResults: z.number().optional().describe("Maximum results to return"),
      },
    },
    async ({ query }) => {
      try {
        const result = await runKicadMcp("search_kicad_docs", { query });
        return { content: [{ type: "text" as const, text: result }] };
      } catch {
        return {
          content: [{
            type: "text" as const,
            text: `KiCad documentation search for "${query}" — use https://docs.kicad.org for latest docs.`,
          }],
        };
      }
    },
  );

  mcp.registerTool(
    "analyze_uploaded_kicad_project",
    {
      annotations: LOCAL_READ_ONLY_ANNOTATIONS,
      description:
        "Analyze an uploaded KiCad project archive. " +
        "Accepts a directory path containing .kicad_proj, .kicad_pcb, .kicad_sch files. " +
        "Returns project metadata, layer stackup, component count, and board statistics.",
      inputSchema: {
        fileId: z.string().describe("Uploaded file identifier or project directory path"),
      },
    },
    async ({ fileId }) => {
      const cached = projects.get(fileId);
      if (cached) {
        const board = cached.boardPath ? analyzePcbFile(cached.boardPath) : null;
        return {
          content: [
            {
              type: "text" as const,
              text: [
                `## Project: ${cached.name}`,
                `- Board: ${cached.boardPath || "N/A"}`,
                `- Schematic: ${cached.schematicPath || "N/A"}`,
                board
                  ? [
                      `- Layers: ${board.layers} (${board.copperLayers} copper)`,
                      `- Components: ${board.componentCount}`,
                      `- Tracks: ${board.trackCount}`,
                      `- Vias: ${board.viaCount}`,
                      board.boardThickness ? `- Board Thickness: ${board.boardThickness}mm` : "",
                    ].filter(Boolean).join("\n")
                  : "",
                "",
                "Upload a KiCad project archive to get full analysis.",
              ].join("\n"),
            },
          ],
        };
      }

      try {
        const safeProjectDir = resolveSafeWorkspaceDirectory(fileId, "fileId");
        const projPath = await extractProject(safeProjectDir);
        const name = projPath.replace(/\.kicad_proj$/, "").split(/[/\\]/).pop() || "unknown";
        const boardPath = resolveProjectSibling(projPath, ".kicad_pcb");
        const board = safeExists(boardPath) ? analyzePcbFile(boardPath) : null;
        return {
          content: [
            {
              type: "text" as const,
              text: [
                `## Project: ${name}`,
                board
                  ? [
                      `- Layers: ${board.layers} (${board.copperLayers} copper)`,
                      `- Components: ${board.componentCount}`,
                      `- Tracks: ${board.trackCount}`,
                      `- Vias: ${board.viaCount}`,
                    ].join("\n")
                  : "Board file not found in archive.",
                "",
                "Upload a complete KiCad project (kicad_proj + kicad_pcb + kicad_sch) for full analysis.",
              ].join("\n"),
            },
          ],
        };
      } catch {
        return {
          content: [{
            type: "text" as const,
            text: `Project "${fileId}" not found. Upload a KiCad project archive (.zip, .kicad_proj) first.`,
          }],
        };
      }
    },
  );

  mcp.registerTool(
    "explain_drc_report",
    {
      annotations: LOCAL_READ_ONLY_ANNOTATIONS,
      description:
        "Interpret a DRC (Design Rule Check) report and explain issues. " +
        "Accepts raw report text and returns a structured summary with categorized violations.",
      inputSchema: {
        reportText: z.string().describe("Raw DRC report text"),
      },
    },
    async ({ reportText }) => {
      const { errors, warnings, issues } = analyzeDrcReport(reportText);
      const lines = [
        `## DRC Report Summary`,
        `- **Errors:** ${errors}`,
        `- **Warnings:** ${warnings}`,
        "",
      ];
      if (issues.length > 0) {
        lines.push("### Issues Found");
        for (const issue of issues.slice(0, 20)) {
          lines.push(`- [${issue.severity.toUpperCase()}] \`${issue.rule}\`: ${issue.description}`);
        }
      }
      lines.push(
        "",
        "### Tips",
        "- Check clearance, track width, and via size constraints",
        "- Verify net classes match design requirements",
        "- Ensure all unrouted nets are intentional",
        "- Run `kicad_run_drc` from the KiCad MCP toolset for a fresh check",
      );
      return { content: [{ type: "text" as const, text: lines.join("\n") }] };
    },
  );

  mcp.registerTool(
    "explain_erc_report",
    {
      annotations: LOCAL_READ_ONLY_ANNOTATIONS,
      description:
        "Interpret an ERC (Electrical Rule Check) report and explain issues. " +
        "Accepts raw report text and returns a structured summary.",
      inputSchema: {
        reportText: z.string().describe("Raw ERC report text"),
      },
    },
    async ({ reportText }) => {
      const { errors, warnings, issues } = analyzeErcReport(reportText);
      const lines = [
        `## ERC Report Summary`,
        `- **Errors:** ${errors}`,
        `- **Warnings:** ${warnings}`,
        "",
      ];
      if (issues.length > 0) {
        lines.push("### Issues Found");
        for (const issue of issues.slice(0, 20)) {
          lines.push(`- [${issue.severity.toUpperCase()}] \`${issue.rule}\`: ${issue.description}`);
        }
      }
      lines.push(
        "",
        "### Tips",
        "- Verify power flags on all power nets",
        "- Check pin conflicts and unconnected pins",
        "- Ensure hierarchical labels match across sheets",
        "- Run `kicad_run_erc` from the KiCad MCP toolset for a fresh check",
      );
      return { content: [{ type: "text" as const, text: lines.join("\n") }] };
    },
  );

  mcp.registerTool(
    "generate_manufacturing_readiness_report",
    {
      annotations: LOCAL_READ_ONLY_ANNOTATIONS,
      description:
        "Generate a manufacturing readiness report for a KiCad project. " +
        "Evaluates DRC/ERC status, BOM, and Gerber availability.",
      inputSchema: {
        drcErrors: z.number().describe("Number of DRC errors"),
        ercErrors: z.number().describe("Number of ERC errors"),
        hasBom: z.boolean().describe("Whether BOM is available"),
        hasGerbers: z.boolean().describe("Whether Gerber files are available"),
        projectName: z.string().optional().describe("Project name"),
      },
    },
    async (input) => {
      const { overall, checks } = generateReadinessChecklist(
        input.drcErrors,
        input.ercErrors,
        input.hasBom,
        input.hasGerbers,
      );
      const header = input.projectName
        ? `## Manufacturing Readiness: ${input.projectName}`
        : "## Manufacturing Readiness Report";
      const statusLine = overall === "ready"
        ? "✅ **Ready for manufacturing**"
        : "❌ **Not ready for manufacturing**";
      const lines = [header, "", statusLine, "", "### Checklist", ""];
      for (const check of checks) {
        const icon = check.passed ? "✅" : "❌";
        lines.push(`| ${icon} | ${check.name} | ${check.detail} |`);
      }
      if (overall !== "ready") {
        lines.push(
          "",
          "### Next Steps",
          ...checks.filter((c) => !c.passed).map((c) => `- Fix: ${c.name} — ${c.detail}`),
        );
      }
      return { content: [{ type: "text" as const, text: lines.join("\n") }] };
    },
  );

  mcp.registerTool(
    "generate_agent_config",
    {
      annotations: LOCAL_READ_ONLY_ANNOTATIONS,
      description: "Generate an MCP configuration snippet for a supported AI coding agent.",
      inputSchema: {
        targetAgent: z
          .enum(["claude-code", "codex", "gemini", "opencode", "cursor", "vscode", "claude-desktop"])
          .describe("Target AI coding agent"),
        mode: z.enum(["readonly", "write"]).optional().describe("Operating mode"),
        transport: z.enum(["stdio", "sse", "streamable-http"]).optional().describe("Transport protocol"),
      },
    },
    async ({ targetAgent, mode = "readonly", transport = "stdio" }) => {
      const env = {
        KICAD_MCP_PROFILE: "readonly",
        KICAD_MCP_OPERATING_MODE: mode,
      };
      const stdioEntry = transport === "stdio"
        ? { command: "uvx", args: ["kicad-mcp-pro"] }
        : { url: process.env.KICAD_MCP_URL || "http://localhost:8412/mcp", env };
      const configs: Record<string, object> = {
        "claude-code": { mcpServers: { kicad: { type: "stdio", ...stdioEntry, env } } },
        codex: { mcp_servers: { kicad: { command: "uvx", args: ["kicad-mcp-pro"], env } } },
        gemini: { mcpServers: { kicad: { ...stdioEntry, env } } },
        opencode: { mcp: { kicad: { type: "local", command: ["uvx", "kicad-mcp-pro"], environment: env } } },
        cursor: { mcpServers: { kicad: { ...stdioEntry, env } } },
        vscode: { servers: { kicad: { type: "stdio", ...stdioEntry, env } } },
        "claude-desktop": { mcpServers: { kicad: { ...stdioEntry, env } } },
      };
      return {
        content: [
          {
            type: "text" as const,
            text: `## Config for ${targetAgent} (${mode}, ${transport})\n\`\`\`json\n${JSON.stringify(configs[targetAgent] || configs["claude-code"], null, 2)}\n\`\`\``,
          },
        ],
      };
    },
  );

  return mcp;
}

async function handleMcpPostRequest(req: Request, res: Response): Promise<void> {
  const server = createMcpServer();
  const transport = new StreamableHTTPServerTransport({ sessionIdGenerator: undefined });
  try {
    await server.connect(transport);
    await transport.handleRequest(req, res, req.body);
    res.on("close", () => {
      void transport.close();
      void server.close();
    });
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    console.error("Error handling MCP POST request:", message);
    if (!res.headersSent) {
      res.status(500).json({
        jsonrpc: "2.0",
        error: { code: -32603, message: "Internal server error" },
        id: null,
      });
    }
  }
}

app.post("/mcp", async (req: Request, res: Response) => { await handleMcpPostRequest(req, res); });
app.get("/mcp", (_req: Request, res: Response) => {
  res.status(405).json({
    jsonrpc: "2.0",
    error: { code: -32000, message: "Method not allowed." },
    id: null,
  });
});
app.delete("/mcp", (_req: Request, res: Response) => {
  res.status(405).json({
    jsonrpc: "2.0",
    error: { code: -32000, message: "Method not allowed." },
    id: null,
  });
});

// Start server
app.listen(PORT, HOST, () => {
  console.log(`KiCad MCP ChatGPT App running at http://${HOST}:${PORT}`);
  console.log(`  MCP endpoint: http://${HOST}:${PORT}/mcp`);
  console.log(`  Dashboard:    http://${HOST}:${PORT}/widgets/kicad-dashboard.html`);
  console.log(`  Project Review: http://${HOST}:${PORT}/widgets/project-review.html`);
  console.log(`  Manufacturing:  http://${HOST}:${PORT}/widgets/manufacturing-report.html`);
});
