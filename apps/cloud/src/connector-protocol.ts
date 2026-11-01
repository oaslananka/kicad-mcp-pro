import { z } from "zod";

// Transport envelope only. It does not enroll a device, mint credentials,
// authorize a project or start a native KiCad operation.
export const CONNECTOR_PROTOCOL_VERSION = 1 as const;
export const MAX_READ_DEADLINE_MS = 30_000;

export const ReadOperationSchema = z.enum([
  "project_summary",
  "run_drc",
  "run_erc"
]);
export type ReadOperation = z.infer<typeof ReadOperationSchema>;

export const ConnectorHelloSchema = z.strictObject({
  kind: z.literal("connector.hello"),
  version: z.literal(CONNECTOR_PROTOCOL_VERSION),
  deviceId: z.uuid(),
  instanceId: z.uuid(),
  engineVersion: z.string().min(1).max(80).regex(/^[a-zA-Z0-9][a-zA-Z0-9.+_-]*$/),
  capabilities: z.array(ReadOperationSchema).max(3).refine(
    items => new Set(items).size === items.length,
    "duplicate capability"
  )
});
export type ConnectorHello = z.infer<typeof ConnectorHelloSchema>;

export const ConnectorReadRequestSchema = z.strictObject({
  kind: z.literal("connector.read_request"),
  version: z.literal(CONNECTOR_PROTOCOL_VERSION),
  requestId: z.uuid(),
  deviceId: z.uuid(),
  projectId: z.uuid(),
  operation: ReadOperationSchema,
  deadlineUnixMs: z.number().int().safe().positive()
});
export type ConnectorReadRequest = z.infer<typeof ConnectorReadRequestSchema>;

/**
 * Verified identity/policy comes from authentication and current server-side
 * grants, never from the untrusted connector frame or an MCP tool argument.
 * The local connector must independently re-check its own project allowlist.
 */
export interface VerifiedReadBoundary {
  readonly authenticatedDeviceId: string;
  readonly authorizedProjectId: string;
  readonly allowedOperations: readonly ReadOperation[];
}

export function parseConnectorHello(raw: unknown, authenticatedDeviceId: string): ConnectorHello | null {
  const parsed = ConnectorHelloSchema.safeParse(raw);
  if (!parsed.success || parsed.data.deviceId !== authenticatedDeviceId) return null;
  return parsed.data;
}

export function parseBoundReadRequest(
  raw: unknown, boundary: VerifiedReadBoundary, nowUnixMs: number
): ConnectorReadRequest | null {
  const parsed = ConnectorReadRequestSchema.safeParse(raw);
  if (!parsed.success || !Number.isSafeInteger(nowUnixMs) || nowUnixMs < 0) return null;
  const message = parsed.data;
  if (message.deviceId !== boundary.authenticatedDeviceId ||
      message.projectId !== boundary.authorizedProjectId ||
      !boundary.allowedOperations.includes(message.operation)) return null;
  // No queued or delayed reads. Inclusive expiry and far-future deadlines fail closed.
  if (message.deadlineUnixMs <= nowUnixMs ||
      message.deadlineUnixMs - nowUnixMs > MAX_READ_DEADLINE_MS) return null;
  return message;
}
