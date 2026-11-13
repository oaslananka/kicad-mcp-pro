import type { Pool } from "pg";
import { createHash } from "node:crypto";

export type ToolCallStatus = "success" | "error" | "denied";
const STATUS_VALUES = new Set<ToolCallStatus>(["success", "error", "denied"]);
const MAX_TOOL = 128;
const MAX_OWNER = 256;
const MAX_CLIENT = 1024;

/**
 * Extract a single deterministic tool call from one JSON-RPC request body.
 * Returns null for everything that cannot be attributed with certainty:
 * non-tool traffic, malformed payloads and unbounded tool names.
 */
export function extractToolCall(body: string): { id: unknown; tool: string } | null {
  if (!body || body.length > 1024 * 1024) return null;
  let parsed: unknown;
  try { parsed = JSON.parse(body); } catch { return null; }
  const request = Array.isArray(parsed) && parsed.length === 1 ? parsed[0] : parsed;
  if (!request || typeof request !== "object" || Array.isArray(request)) return null;
  const record = request as Record<string, unknown>;
  if (record.jsonrpc !== "2.0" || record.method !== "tools/call") return null;
  const params = record.params;
  if (!params || typeof params !== "object" || Array.isArray(params)) return null;
  const tool = (params as Record<string, unknown>).name;
  if (typeof tool !== "string" || tool.length < 1 || tool.length > MAX_TOOL ||
      !/^[\w.-]+$/.test(tool)) return null;
  return { id: record.id, tool };
}

/**
 * Map one JSON-RPC response to an honest outcome for the matching request.
 * A protocol-level error means the call was refused ("denied"); an isError
 * tool result means the tool ran and failed ("error"); anything else that
 * matches the request id is "success". Unmatchable bodies record nothing.
 */
export function callStatusFromResponse(
  body: string, requestId: unknown
): ToolCallStatus | null {
  if (!body || body.length > 1024 * 1024) return null;
  let parsed: unknown;
  try { parsed = JSON.parse(body); } catch { return null; }
  const response = Array.isArray(parsed) && parsed.length === 1 ? parsed[0] : parsed;
  if (!response || typeof response !== "object" || Array.isArray(response)) return null;
  const record = response as Record<string, unknown>;
  if (record.jsonrpc !== "2.0") return null;
  if (!("id" in record) || !sameId(record.id, requestId)) return null;
  if ("error" in record) return "denied";
  const result = record.result;
  if (!result || typeof result !== "object" || Array.isArray(result)) return "success";
  return (result as Record<string, unknown>).isError === true ? "error" : "success";
}

function sameId(a: unknown, b: unknown): boolean {
  if (a === null || a === undefined || typeof a === "object" ||
      b === null || b === undefined || typeof b === "object") return false;
  return String(a) === String(b);
}

/** Aggregated, observation-only usage. No quota or allowance exists here. */
export type UsageSummary = {
  windowDays: number;
  totalCalls: number;
  byTool: Array<{ tool: string; count: number }>;
  byClient: Array<{ clientId: string; count: number }>;
  byStatus: Array<{ status: ToolCallStatus; count: number }>;
  byDay: Array<{ day: string; calls: number }>;
  firstAt: string | null;
  lastAt: string | null;
};
export type UsageEvent = {
  id: number;
  at: string;
  tool: string;
  clientId: string;
  status: ToolCallStatus;
};
export type Cursor = { id: number; at: string };

export class PgUsage {
  constructor(private readonly pool: Pool) {}

  /** Bounded write of one observed call. Invalid values are refused. */
  async record(ownerSub: string, clientId: string,
    tool: string, status: ToolCallStatus): Promise<void> {
    if (!ownerSub || ownerSub.length > MAX_OWNER) return;
    if (!clientId || clientId.length > MAX_CLIENT) return;
    if (!tool || tool.length > MAX_TOOL || !/^[\w.-]+$/.test(tool)) return;
    if (!STATUS_VALUES.has(status)) return;
    try {
      await this.pool.query(
        "INSERT INTO usage_tool_calls(owner_sub,client_id,tool,status) VALUES($1,$2,$3,$4)",
        [ownerSub, clientId, tool, status]);
    } catch {
      // Telemetry must never turn a served tool call into a failed one.
    }
  }

  async summary(ownerSub: string, windowDays = 30): Promise<UsageSummary | null> {
    if (!ownerSub || ownerSub.length > MAX_OWNER || !Number.isInteger(windowDays) ||
        windowDays < 1 || windowDays > 365) return null;
    const within = await this.pool.query<{ tool: string; client_id: string; status: ToolCallStatus; n: string }>(
      "SELECT tool,client_id,status,count(*)::text AS n FROM usage_tool_calls "+
      "WHERE owner_sub=$1 AND occurred_at >= statement_timestamp() - make_interval(days => $2) "+
      "GROUP BY tool,client_id,status",[ownerSub, windowDays]);
    if (!within.rows.length) return null;
    const daily = await this.pool.query<{ day: string; n: string }>(
      "SELECT to_char(date_trunc('day',occurred_at),'YYYY-MM-DD') AS day,count(*)::text AS n "+
      "FROM usage_tool_calls WHERE owner_sub=$1 "+
      "AND occurred_at >= statement_timestamp() - make_interval(days => $2) "+
      "GROUP BY 1 ORDER BY 1",[ownerSub, windowDays]);
    const bounds = await this.pool.query<{ first_at: Date | null; last_at: Date | null }>(
      "SELECT min(occurred_at) AS first_at,max(occurred_at) AS last_at FROM usage_tool_calls "+
      "WHERE owner_sub=$1 AND occurred_at >= statement_timestamp() - make_interval(days => $2)",
      [ownerSub, windowDays]);
    const byTool = new Map<string, number>();
    const byClient = new Map<string, number>();
    const byStatus = new Map<ToolCallStatus, number>();
    let total = 0;
    for (const row of within.rows) {
      const count = Number(row.n);
      total += count;
      byTool.set(row.tool, (byTool.get(row.tool) ?? 0) + count);
      byClient.set(row.client_id, (byClient.get(row.client_id) ?? 0) + count);
      byStatus.set(row.status, (byStatus.get(row.status) ?? 0) + count);
    }
    const descending = (a: [string, number], b: [string, number]) =>
      b[1] - a[1] || (a[0] < b[0] ? -1 : 1);
    const statusOrder: ToolCallStatus[] = ["success", "denied", "error"];
    return {
      windowDays, totalCalls: total,
      byTool: [...byTool.entries()].sort(descending).slice(0, 50)
        .map(([tool, count]) => ({ tool, count })),
      byClient: [...byClient.entries()].sort(descending).slice(0, 50)
        .map(([clientId, count]) => ({ clientId, count })),
      byStatus: statusOrder.filter(s => byStatus.has(s))
        .map(status => ({ status, count: byStatus.get(status)! })),
      byDay: daily.rows.map(r => ({ day: r.day, calls: Number(r.n) })),
      firstAt: bounds.rows[0]?.first_at?.toISOString() ?? null,
      lastAt: bounds.rows[0]?.last_at?.toISOString() ?? null
    };
  }

  /** Newest-first safe-field events for one owner. */
  async recent(ownerSub: string, limit = 50, beforeId?: number): Promise<UsageEvent[]> {
    if (!ownerSub || ownerSub.length > MAX_OWNER || !Number.isInteger(limit) ||
        limit < 1 || limit > 200) return [];
    const params: unknown[] = [ownerSub, limit];
    let filter = "";
    if (beforeId !== undefined) {
      if (!Number.isSafeInteger(beforeId) || beforeId < 1) return [];
      params.push(beforeId);
      filter = " AND id < $3";
    }
    const rows = await this.pool.query<{
      id: string; occurred_at: Date; tool: string; client_id: string; status: ToolCallStatus;
    }>(
      "SELECT id,occurred_at,tool,client_id,status FROM usage_tool_calls "+
      "WHERE owner_sub=$1"+filter+" ORDER BY id DESC LIMIT $2", params);
    return rows.rows.map(r => ({
      id: Number(r.id), at: r.occurred_at.toISOString(),
      tool: r.tool, clientId: r.client_id, status: r.status
    }));
  }

  /**
   * Remove another owner's rows from the visible log stream. The returned
   * cursor never exposes another owner's event identity or timestamp.
   */
  async cursorBefore(ownerSub: string, id: number): Promise<Cursor | null> {
    if (!ownerSub || ownerSub.length > MAX_OWNER || !Number.isSafeInteger(id) || id < 1)
      return null;
    const row = await this.pool.query<{ occurred_at: Date; owner_sub: string }>(
      "SELECT occurred_at,owner_sub FROM usage_tool_calls WHERE id=$1 LIMIT 1", [id]);
    if (row.rows[0]?.owner_sub !== ownerSub) return null;
    return { id, at: row.rows[0].occurred_at.toISOString() };
  }
}

/** Only a hash is ever persisted; the plaintext token never lands in SQL. */
export function hashToken(token: string): string {
  return createHash("sha256").update(token, "utf8").digest("hex");
}

/** Read surface used by the authenticated /usage browser page. */
export interface UsagePort {
  summary(ownerSub: string, windowDays?: number): Promise<UsageSummary | null>;
  recent(ownerSub: string, limit?: number): Promise<UsageEvent[]>;
}
