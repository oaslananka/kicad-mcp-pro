import assert from "node:assert/strict";
import { test } from "node:test";
import {
  CONNECTOR_PROTOCOL_VERSION, parseBoundReadRequest, parseConnectorHello,
  type VerifiedReadBoundary
} from "../src/connector-protocol.js";

const DEVICE = "5f19d34e-946f-4b27-a3dd-0d5dc4599017";
const OTHER_DEVICE = "d5a81131-a24f-4a9c-a651-0adf3846628e";
const PROJECT = "113956f7-6a78-497d-8a42-a8b2a9fd8864";
const OTHER_PROJECT = "7bf8dd5e-e6d1-4d2a-86b4-3b454103b251";
const ID = "39a0c743-969d-4ad4-802e-60a3c8a7c168";
const now = 1_780_000_000_000;
const boundary: VerifiedReadBoundary = {
  authenticatedDeviceId: DEVICE, authorizedProjectId: PROJECT,
  allowedOperations: ["project_summary", "run_drc"]
};
const hello = () => ({
  kind: "connector.hello", version: CONNECTOR_PROTOCOL_VERSION, deviceId: DEVICE,
  instanceId: ID, engineVersion: "2.1.0", capabilities: ["project_summary", "run_drc"]
});
const read = () => ({
  kind: "connector.read_request", version: CONNECTOR_PROTOCOL_VERSION,
  requestId: ID, deviceId: DEVICE, projectId: PROJECT,
  operation: "run_drc", deadlineUnixMs: now + 10_000
});

test("connector hello is strict, versioned and device-bound", () => {
  assert.equal(parseConnectorHello(hello(), DEVICE)?.deviceId, DEVICE);
  assert.equal(parseConnectorHello(hello(), OTHER_DEVICE), null);
  assert.equal(parseConnectorHello({ ...hello(), version: 2 }, DEVICE), null);
  assert.equal(parseConnectorHello({ ...hello(), localPath: "/private/projects" }, DEVICE), null);
  assert.equal(parseConnectorHello({ ...hello(), authorization: "Bearer secret" }, DEVICE), null);
  assert.equal(parseConnectorHello({ ...hello(), capabilities: ["run_drc", "run_drc"] }, DEVICE), null);
  assert.equal(parseConnectorHello({ ...hello(), capabilities: ["shell.execute"] }, DEVICE), null);
  assert.equal(parseConnectorHello({ ...hello(), engineVersion: "../etc" }, DEVICE), null);
  assert.equal(parseConnectorHello(null, DEVICE), null);
});

test("read request needs independently verified device, project and operation", () => {
  assert.equal(parseBoundReadRequest(read(), boundary, now)?.operation, "run_drc");
  assert.equal(parseBoundReadRequest({ ...read(), deviceId: OTHER_DEVICE }, boundary, now), null);
  assert.equal(parseBoundReadRequest({ ...read(), projectId: OTHER_PROJECT }, boundary, now), null);
  assert.equal(parseBoundReadRequest({ ...read(), operation: "run_erc" }, boundary, now), null);
  assert.equal(parseBoundReadRequest({ ...read(), operation: "invoke_any_tool" }, boundary, now), null);
  assert.equal(parseBoundReadRequest({ ...read(), path: "C:\\\\Private\\\\PCB" }, boundary, now), null);
  assert.equal(parseBoundReadRequest({ ...read(), capabilities: ["shell.execute"] }, boundary, now), null);
  assert.equal(parseBoundReadRequest({ ...read(), version: 0 }, boundary, now), null);
});

test("bounded deadline rejects expiry, far future, invalid clocks and malformed IDs", () => {
  assert.equal(parseBoundReadRequest({ ...read(), deadlineUnixMs: now }, boundary, now), null);
  assert.equal(parseBoundReadRequest({ ...read(), deadlineUnixMs: now - 1 }, boundary, now), null);
  assert.equal(parseBoundReadRequest({ ...read(), deadlineUnixMs: now + 30_001 }, boundary, now), null);
  assert.equal(parseBoundReadRequest({ ...read(), deadlineUnixMs: now + 30_000 }, boundary, now)?.requestId, ID);
  assert.equal(parseBoundReadRequest({ ...read(), deadlineUnixMs: 1e200 }, boundary, now), null);
  assert.equal(parseBoundReadRequest({ ...read(), requestId: "not-a-uuid" }, boundary, now), null);
  assert.equal(parseBoundReadRequest(read(), boundary, Number.NaN), null);
});
