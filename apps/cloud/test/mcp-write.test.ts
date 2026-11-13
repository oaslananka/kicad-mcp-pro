import test from "node:test";
import assert from "node:assert/strict";
import type { AddressInfo } from "node:net";
import { generateKeyPairSync } from "node:crypto";
import { createHttpServer } from "../src/http.js";
import { createOfflineSignedWriteProposal } from "../src/connector-write-proof.js";
import type { Config } from "../src/config.js";
import type { Inventory, Project } from "../src/store.js";
import type { Verifier, Actor } from "../src/auth.js";
import type { TrustedOAuthReadIdentity } from "../src/connector-read-gate.js";

const config: Config = {
  port: 0,
  host: "127.0.0.1",
  publicOrigin: "http://127.0.0.1",
  issuer: "https://issuer.example",
  jwksUrl: "https://issuer.example/keys",
  audience: "http://127.0.0.1/mcp",
  databaseUrl: "postgres://mock",
  allowedOrigins: [],
  managementClientId: "portal-client"
};

const edKey = generateKeyPairSync("ed25519");

const projectId = "22222222-2222-4222-8222-222222222222";
const deviceId = "11111111-1111-4111-8111-111111111111";
const sessionId = "33333333-3333-4333-8333-333333333333";
const connectionBinding = "A".repeat(43);

const mockProject: Project = {
  id: projectId,
  deviceId,
  alias: "Mock Board",
  enabled: true,
  maxMode: "write",
  available: false,
  reason: "cloud_read_not_enabled"
};

test("pcb_move_footprint MCP write tool end-to-end verification", async () => {
  let tokenValid = true;
  let writeExecuted = false;
  let preflightAllowed = true;

  const inventory: Inventory = {
    async listProjects(sub, client) {
      if (sub !== "user-a" || client !== "test-client") return [];
      return [mockProject];
    },
    async getProject(sub, client, id) {
      if (sub !== "user-a" || client !== "test-client" || id !== projectId) return null;
      return mockProject;
    },
    async listDevices() { return []; },
    async isAccessTokenAllowed() { return tokenValid; }
  };

  const verify: Verifier = async (token: string): Promise<Actor> => {
    if (token === "token-read-only") {
      return {
        sub: "user-a",
        clientId: "test-client",
        scopes: new Set(["projects:read"]),
        issuedAt: Math.floor(Date.now() / 1000)
      };
    }
    if (token === "token-write") {
      return {
        sub: "user-a",
        clientId: "test-client",
        scopes: new Set(["projects:read", "projects:write"]),
        issuedAt: Math.floor(Date.now() / 1000)
      };
    }
    if (token === "token-foreign") {
      return {
        sub: "user-b",
        clientId: "foreign-client",
        scopes: new Set(["projects:read", "projects:write"]),
        issuedAt: Math.floor(Date.now() / 1000)
      };
    }
    throw Error("invalid_token");
  };

  const relay = {
    prepareOwnerSummary: () => null,
    requestSummary: async () => null,
    isDeviceConnected: () => true,
    getTrustedContext: (ownerSub: string, devId: string) => {
      if (ownerSub !== "user-a" || devId !== deviceId) return null;
      return { deviceId, sessionId, connectionBinding };
    },
    prepareWriteRevisions: async (ownerSub: string, devId: string, projId: string) => {
      if (ownerSub !== "user-a" || devId !== deviceId || projId !== projectId) return null;
      return {
        expectedBoardSha256: "0".repeat(64),
        expectedLiveBoardSha256: "1".repeat(64)
      };
    },
    requestWrite: async (
      _oauth: TrustedOAuthReadIdentity,
      _devId: string,
      projId: string,
      proof: object,
      persistToDisk: boolean
    ) => {
      writeExecuted = true;
      const proposal = proof as { payload: string };
      const parsed = JSON.parse(Buffer.from(proposal.payload, "base64url").toString("utf8"));
      return {
        requestId: parsed.requestId,
        projectId: projId,
        operation: "pcb_move_footprint" as const,
        nativeCommitted: true,
        savedToDisk: persistToDisk,
        diskBoardSha256: "2".repeat(64)
      };
    }
  };

  const writeIssuer = (candidate: unknown, binding: any, nowMs: number) => {
    return createOfflineSignedWriteProposal(candidate, binding, nowMs, edKey.privateKey);
  };

  const writePreflight = {
    checkCurrentPolicy: async () => preflightAllowed,
    reserveAuthorizedWrite: async () => preflightAllowed
  };

  const disabledServer = createHttpServer(config, inventory, verify, {
    summaryRelay: () => relay as never,
    mcpProjectWriteEnabled: false
  });

  const enabledServer = createHttpServer(config, inventory, verify, {
    summaryRelay: () => relay as never,
    mcpProjectWriteEnabled: true,
    writeIssuer,
    writePreflight: writePreflight as never
  });

  try {
    await new Promise<void>(resolve => disabledServer.listen(0, "127.0.0.1", resolve));
    await new Promise<void>(resolve => enabledServer.listen(0, "127.0.0.1", resolve));

    const disabledOrigin = "http://127.0.0.1:" + (disabledServer.address() as AddressInfo).port;
    const enabledOrigin = "http://127.0.0.1:" + (enabledServer.address() as AddressInfo).port;

    const invoke = async (origin: string, token: string, method: string, params: Record<string, any> = {}, id = 1, toolName?: string) => {
      const res = await fetch(origin + "/mcp", {
        method: "POST",
        headers: {
          "Authorization": "Bearer " + token,
          "Content-Type": "application/json",
          "Accept": "application/json, text/event-stream",
          "MCP-Protocol-Version": "2026-07-28",
          "Mcp-Method": method,
          ...(toolName ? { "Mcp-Name": toolName } : {})
        },
        body: JSON.stringify({
          jsonrpc: "2.0",
          id,
          method,
          params: {
            ...params,
            _meta: {
              "io.modelcontextprotocol/clientInfo": { name: "test-client", version: "1.0.0" },
              "io.modelcontextprotocol/protocolVersion": "2026-07-28",
              "io.modelcontextprotocol/clientCapabilities": {}
            }
          }
        })
      });
      const text = await res.text();
      let data: Record<string, any> = {};
      if (text.startsWith("event: message\ndata: ")) {
        const line = text.split("\n").find(l => l.startsWith("data: "));
        if (line) data = JSON.parse(line.slice(6));
      } else if (text) {
        try { data = JSON.parse(text); } catch { data = { raw: text }; }
      }
      return { status: res.status, data };
    };

    // 1. Tool is absent when write is disabled
    const listDisabled = await invoke(disabledOrigin, "token-write", "tools/list", {}, 1);
    const disabledTools = (listDisabled.data.result?.tools ?? []).map((t: { name: string }) => t.name);
    assert.equal(disabledTools.includes("pcb_move_footprint"), false);

    // 2. Tool is present when write is enabled
    const listEnabled = await invoke(enabledOrigin, "token-write", "tools/list", {}, 2);
    const enabledTools = (listEnabled.data.result?.tools ?? []).map((t: { name: string }) => t.name);
    assert.equal(enabledTools.includes("pcb_move_footprint"), true);

    // 3. Insufficient scope (read-only token)
    const readOnlyCall = await invoke(enabledOrigin, "token-read-only", "tools/call", {
      name: "pcb_move_footprint",
      arguments: { project_id: projectId, reference: "R1", x_mm: 10, y_mm: 20 }
    }, 3, "pcb_move_footprint");
    assert.equal(readOnlyCall.status, 200);
    assert.match(JSON.stringify(readOnlyCall.data), /insufficient_scope_write_required/);
    assert.equal(writeExecuted, false);

    // 4. Foreign client / user
    const foreignCall = await invoke(enabledOrigin, "token-foreign", "tools/call", {
      name: "pcb_move_footprint",
      arguments: { project_id: projectId, reference: "R1", x_mm: 10, y_mm: 20 }
    }, 4, "pcb_move_footprint");
    assert.equal(foreignCall.status, 200);
    assert.match(JSON.stringify(foreignCall.data), /"success":false/);
    assert.equal(writeExecuted, false);

    // 5. Successful write execution with disk save
    const successCall = await invoke(enabledOrigin, "token-write", "tools/call", {
      name: "pcb_move_footprint",
      arguments: {
        project_id: projectId,
        reference: "R1",
        x_mm: 15.5,
        y_mm: -20.25,
        rotation_deg: 90,
        save_to_disk: true
      }
    }, 5, "pcb_move_footprint");
    assert.equal(successCall.status, 200);
    assert.equal(writeExecuted, true);
    assert.match(JSON.stringify(successCall.data), /"success":true/);
    assert.match(JSON.stringify(successCall.data), /"nativeCommitted":true/);
    assert.match(JSON.stringify(successCall.data), /"savedToDisk":true/);
    assert.match(JSON.stringify(successCall.data), /"diskBoardSha256":"2222/);

    // 6. Preflight denial fails closed
    writeExecuted = false;
    preflightAllowed = false;
    const deniedCall = await invoke(enabledOrigin, "token-write", "tools/call", {
      name: "pcb_move_footprint",
      arguments: { project_id: projectId, reference: "R1", x_mm: 0, y_mm: 0 }
    }, 6, "pcb_move_footprint");
    assert.equal(deniedCall.status, 200);
    assert.match(JSON.stringify(deniedCall.data), /"success":false/);
    assert.equal(writeExecuted, false);

    // 7. Token revocation fails closed
    preflightAllowed = true;
    tokenValid = false;
    const revokedCall = await invoke(enabledOrigin, "token-write", "tools/call", {
      name: "pcb_move_footprint",
      arguments: { project_id: projectId, reference: "R1", x_mm: 0, y_mm: 0 }
    }, 7, "pcb_move_footprint");
    assert.equal(revokedCall.status, 401);
    assert.equal(writeExecuted, false);

  } finally {
    if (disabledServer.listening) await new Promise<void>(resolve => disabledServer.close(() => resolve()));
    if (enabledServer.listening) await new Promise<void>(resolve => enabledServer.close(() => resolve()));
  }
});
