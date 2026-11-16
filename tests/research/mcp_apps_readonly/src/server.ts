import { readFile } from "node:fs/promises";
import { createMcpExpressApp } from "@modelcontextprotocol/express";
import { NodeStreamableHTTPServerTransport } from "@modelcontextprotocol/node";
import { McpServer } from "@modelcontextprotocol/server";
import {
  registerAppResource,
  registerAppTool,
  RESOURCE_MIME_TYPE,
} from "@modelcontextprotocol/ext-apps/server";
import { z } from "zod";
import type { Request, Response } from "express";
import { parseReviewFixture, formatTextReview } from "./review-schema.js";

export const TOOL_NAME = "review_kicad_fixture";
export const RESOURCE_URI = "ui://kicad-mcp-pro/readonly-review";
const FIXTURES = {
  "pcb-drc": "pcb-drc.json",
  "schematic-erc": "schematic-erc.json",
  "empty": "empty.json",
};
const CSP = {
  connectDomains: [],
  resourceDomains: [],
  frameDomains: [],
  baseUriDomains: [],
};

export function createFixtureServer(): McpServer {
  const server = new McpServer({ name: "kicad-readonly-research-fixture", version: "0.0.0" });
  registerAppTool(
    server,
    TOOL_NAME,
    {
      title: "Review a synthetic KiCad design",
      description: "Inspect a static, synthetic PCB/DRC or schematic/ERC fixture. Never accesses KiCad, project files or write tools.",
      inputSchema: z.object({ variant: z.enum(["pcb-drc", "schematic-erc", "empty"]).optional() }).strict(),
      annotations: { readOnlyHint: true, destructiveHint: false, openWorldHint: false },
      _meta: { ui: { resourceUri: RESOURCE_URI, visibility: ["model"] } },
    },
    async (args) => {
      const variant = args.variant ?? "pcb-drc";
      const fixtureText = await readFile(
        new URL(`../../../fixtures/${FIXTURES[variant]}`, import.meta.url),
        "utf8",
      );
      const data = parseReviewFixture(JSON.parse(fixtureText));
      return {
        content: [{ type: "text" as const, text: formatTextReview(data) }],
        structuredContent: { ...data },
        isError: false,
      };
    },
  );
  registerAppResource(
    server,
    "Synthetic KiCad Review View",
    RESOURCE_URI,
    {
      description: "Isolated read-only MCP Apps review card",
      mimeType: RESOURCE_MIME_TYPE,
      _meta: { ui: { csp: CSP } },
    },
    async () => ({
      contents: [
        {
          uri: RESOURCE_URI,
          mimeType: RESOURCE_MIME_TYPE,
          text: await readFile(new URL("../../view.html", import.meta.url), "utf8"),
          _meta: { ui: { csp: CSP } },
        },
      ],
    }),
  );
  return server;
}

export async function startFixtureServer(port: number): Promise<void> {
  if (!Number.isInteger(port) || port < 1024 || port > 65535) {
    throw new Error("Invalid local port");
  }
  const host = "127.0.0.1";
  const app = createMcpExpressApp({
    host,
    allowedHosts: ["127.0.0.1", "localhost"],
    allowedOrigins: ["127.0.0.1", "localhost"],
    jsonLimit: "4kb",
  });
  const referenceHostOrigin = "http://localhost:8080";
  app.use((req: Request, res: Response, next) => {
    const origin = req.headers.origin;
    if (origin && origin !== referenceHostOrigin) {
      res.status(403).json({ error: "Origin denied for synthetic fixture" });
      return;
    }
    if (origin) {
      res.setHeader("Vary", "Origin");
      res.setHeader("Access-Control-Allow-Origin", "http://localhost:8080");
      res.setHeader("Access-Control-Allow-Methods", "GET, POST, OPTIONS");
      res.setHeader(
        "Access-Control-Allow-Headers",
        "content-type,accept,mcp-protocol-version,mcp-session-id,last-event-id",
      );
      res.setHeader("Access-Control-Expose-Headers", "mcp-session-id,mcp-protocol-version");
    }
    if (req.method === "OPTIONS" && req.path === "/mcp") {
      res.sendStatus(204);
      return;
    }
    next();
  });
  app.all("/mcp", async (req: Request, res: Response) => {
    const server = createFixtureServer();
    const transport = new NodeStreamableHTTPServerTransport({ sessionIdGenerator: undefined });
    res.on("close", () => {
      void transport.close();
      void server.close();
    });
    try {
      await server.connect(transport);
      await transport.handleRequest(req, res, req.body);
    } catch {
      if (!res.headersSent) {
        res.status(500).json({
          jsonrpc: "2.0",
          error: { code: -32603, message: "Synthetic fixture transport failure" },
          id: null,
        });
      }
    }
  });
  await new Promise<void>((resolve, reject) => {
    const listener = app.listen(port, host, () => {
      console.log(`Synthetic read-only MCP fixture listening: http://127.0.0.1:${port}/mcp`);
      resolve();
    });
    listener.on("error", reject);
  });
}
