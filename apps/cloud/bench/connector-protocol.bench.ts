import { bench, describe } from "vitest";
import { createHash } from "node:crypto";
import {
  parseBoundReadRequest, parseConnectorHello, type VerifiedReadBoundary
} from "../src/connector-protocol.js";
import { signedReadProof } from "../src/connector-read-gate.js";
import { deviceHandshakeProof } from "../src/device-handshake.js";

const deviceId = "7f8b2c1e-4d3a-4b5c-9e6f-0a1b2c3d4e5f";
const projectId = "1a2b3c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d";
const now = 1_780_000_000_000;

const hello = {
  kind: "connector.hello",
  version: 1,
  deviceId,
  instanceId: "9e8d7c6b-5a49-4382-a716-151413121110",
  engineVersion: "kicad-mcp-pro-3.2.1",
  capabilities: ["project_summary", "run_drc", "run_erc"]
};
const boundary: VerifiedReadBoundary = {
  authenticatedDeviceId: deviceId,
  authorizedProjectId: projectId,
  allowedOperations: ["project_summary", "run_drc", "run_erc"]
};
const readRequest = {
  kind: "connector.read_request",
  version: 1,
  requestId: "0f1e2d3c-4b5a-4968-8776-655443322110",
  deviceId,
  projectId,
  operation: "run_drc",
  deadlineUnixMs: now + 10_000
};
const tamperedRequest = { ...readRequest, operation: "write_board", extra: true };
const rawFrame = Buffer.from(JSON.stringify(readRequest), "utf8");
const oauth = { ownerSub: "owner-1", clientId: "chatgpt-client", accessTokenIssuedAtSeconds: 1_780_000_000 };
const connection = {
  deviceId,
  sessionId: "2b3c4d5e-6f70-4182-a3b4-c5d6e7f80910",
  connectionBinding: createHash("sha256").update("binding").digest("base64url")
};

if (!parseConnectorHello(hello, deviceId) || !parseBoundReadRequest(readRequest, boundary, now)) {
  throw new Error("connector protocol fixtures must be valid");
}

describe("connector protocol", () => {
  bench("parseConnectorHello (valid)", () => {
    parseConnectorHello(hello, deviceId);
  });

  bench("parseBoundReadRequest (valid)", () => {
    parseBoundReadRequest(readRequest, boundary, now);
  });

  bench("parseBoundReadRequest (rejected)", () => {
    parseBoundReadRequest(tamperedRequest, boundary, now);
  });

  bench("parse raw read frame and bind", () => {
    parseBoundReadRequest(JSON.parse(rawFrame.toString("utf8")), boundary, now);
  });

  bench("signedReadProof", () => {
    signedReadProof(oauth, connection, 42, rawFrame);
  });

  bench("deviceHandshakeProof", () => {
    deviceHandshakeProof(readRequest.requestId, deviceId, connection.connectionBinding);
  });
});
