import {z} from "zod";

/**
 * Offline-only, untrusted v1 write payload. Neither parsing nor constructing
 * this value authorizes a write, opens a route, or starts a KiCad mutation.
 * The future authenticated Connector must separately verify the owner grant,
 * client OAuth scope, signed one-shot command, local binding, board revision,
 * and KiCad transaction before invoking the native tool.
 *
 * Kept separate from connector-protocol.ts so existing read-only v1 clients
 * cannot discover or interpret this as an advertised capability.
 */
export const WRITE_CONTRACT_VERSION=1 as const;
export const MAX_WRITE_FRAME_BYTES=1024;
export const MAX_WRITE_DEADLINE_MS=10_000;

const BoardRevision=z.string().regex(/^[a-f0-9]{64}$/);
const FootprintReference=z.string().regex(/^[A-Z]{1,3}[1-9][0-9]{0,5}$/);
const Coordinate=z.number().finite().min(-1000).max(1000);
const Angle=z.number().finite().min(-360).max(360);

export const WriteCommandSchema=z.strictObject({
  operation:z.literal("pcb_move_footprint"),
  reference:FootprintReference,
  xMm:Coordinate,
  yMm:Coordinate,
  rotationDeg:Angle.nullable(),
  expectedBoardSha256:BoardRevision
});

export const ConnectorWriteRequestSchema=z.strictObject({
  kind:z.literal("connector.write_request"),
  version:z.literal(WRITE_CONTRACT_VERSION),
  requestId:z.uuid(),
  deviceId:z.uuid(),
  projectId:z.uuid(),
  sessionId:z.uuid(),
  deadlineUnixMs:z.number().int().safe().positive(),
  command:WriteCommandSchema
});
export type ConnectorWriteRequest=z.infer<typeof ConnectorWriteRequestSchema>;

/** Pure shape/binding check. NEVER use this result as proof of consent. */
export function parseUntrustedWriteRequest(
  raw:unknown, binding:Readonly<{
    deviceId:string;projectId:string;sessionId:string;
    sessionExpiresUnixMs:number;allowedOperations:readonly string[];
  }>, nowMs:number
):ConnectorWriteRequest|null{
  if(!Number.isSafeInteger(nowMs)||nowMs<0||!binding||
    !Number.isSafeInteger(binding.sessionExpiresUnixMs)||
    binding.sessionExpiresUnixMs<=nowMs||
    !Array.isArray(binding.allowedOperations))return null;
  // The transport must first enforce wire size and reject duplicate JSON
  // keys. Accepting raw strings here would silently permit last-key-wins.
  if(typeof raw!=="object"||raw===null||Array.isArray(raw))return null;
  const parsed=ConnectorWriteRequestSchema.safeParse(raw);
  if(!parsed.success)return null;
  const value=parsed.data;
  if(value.deviceId!==binding.deviceId||value.projectId!==binding.projectId||
     value.sessionId!==binding.sessionId||value.deadlineUnixMs<=nowMs||
     value.deadlineUnixMs-nowMs>MAX_WRITE_DEADLINE_MS||
     value.deadlineUnixMs>binding.sessionExpiresUnixMs||
     !binding.allowedOperations.includes(value.command.operation))return null;
  // Bound object input as well; parsed objects are not necessarily wire JSON.
  if(Buffer.byteLength(JSON.stringify(value),"utf8")>MAX_WRITE_FRAME_BYTES)return null;
  return value;
}
