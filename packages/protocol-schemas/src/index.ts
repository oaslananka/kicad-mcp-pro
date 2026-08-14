import Ajv2020 from "ajv/dist/2020";
import type { ErrorObject, ValidateFunction } from "ajv";
import { existsSync } from "node:fs";
import { dirname, join, resolve } from "node:path";

export const KICAD_PROTOCOL_SCHEMA_VERSION = "1.0.0";

export const PROTOCOL_SCHEMA_NAMES = [
  "bom-netlist-summary",
  "compatibility-manifest",
  "extension-active-context",
  "kicad-mcp-server-info",
  "mcp-server-health",
  "mcp-tool-capability",
  "mcp-tool-discovery",
  "normalized-diagnostic",
] as const;

export type ProtocolSchemaName = (typeof PROTOCOL_SCHEMA_NAMES)[number];

export interface ProtocolJsonSchema {
  $schema: string;
  $id: string;
  title: string;
  description?: string;
  type: string;
  [key: string]: unknown;
}

export interface ProtocolValidationError {
  path: string;
  message: string;
  keyword: string;
}

export interface ProtocolValidationResult<T = unknown> {
  schemaName: ProtocolSchemaName;
  schemaVersion: string;
  valid: boolean;
  errors: ProtocolValidationError[];
  data?: T;
}

export interface McpServerInfoCompatibilityRange {
  kicadStudio: {
    required: string;
    recommended: string;
    testedAgainst: string;
  };
  kicadMcpPro: {
    required: string;
    testedAgainst: string;
  };
}

export type McpOperatingMode =
  "readonly" | "write" | "manufacturing" | "experimental";

export interface McpToolOperatingModeAvailability {
  available: boolean;
  requiredMode: McpOperatingMode;
  reason: string | null;
}

export interface McpServerInfoContract {
  schemaVersion: string;
  server: "kicad-mcp-pro";
  description?: string;
  localizedDescriptions?: Record<string, string>;
  version: string;
  mcpProtocolVersion: string;
  toolSchemaVersion: string;
  compatibilityRange: McpServerInfoCompatibilityRange;
  transport: {
    type: "stdio" | "streamable-http" | "sse";
    streamableHttp: boolean;
    statelessHttp: boolean;
    legacySse: boolean;
    authRequired: boolean;
    endpoint: string | null;
  };
  kicad: {
    cliFound: boolean;
    cliPath: string;
    cliVersion: string | null;
    ipcAvailable: boolean;
    ipcVersion: string | null;
    ipcApiVersion: string | null;
    ipcMajorVersion: number | null;
    ipcEndpointSource: "config" | "environment" | "default";
    livePcbContext: boolean;
    liveSchematicContext: boolean;
    headlessIpcRequested?: boolean;
    headlessIpcAvailable?: boolean;
    ipcDocumentLoaded: boolean;
  };
  operatingMode: {
    active: McpOperatingMode;
    default: McpOperatingMode;
    available: McpOperatingMode[];
    experimentalEnabled: boolean;
    toolAvailability: Record<string, McpToolOperatingModeAvailability>;
  };
  capabilities: {
    fileBackedDrc: boolean;
    fileBackedErc: boolean;
    fileBackedExports: boolean;
    livePcbRead: boolean;
    livePcbWrite: boolean;
    liveSchematicRead: boolean;
    liveSchematicWrite: boolean;
    liveEditingTools: Record<
      string,
      {
        available: boolean;
        backend: "kicad-ipc" | "kicad-ipc-headless" | "hybrid-file-ipc";
        reason: string | null;
        minimumKiCadMajor: number;
      }
    >;
    chatgptConnectorCompatible: boolean;
    adapterRouting?: {
      schemaVersion: string;
      context: {
        kicadMajor: number | null;
        ipcReachable: boolean;
        livePcbContext: boolean;
        liveSchematicContext: boolean;
        headlessIpcAvailable: boolean;
        cliAvailable: boolean;
        ngspiceAvailable: boolean;
        freeroutingAvailable: boolean;
        dockerAvailable: boolean;
        networkAvailable: boolean;
      };
      categories: Record<
        string,
        {
          preferredBackends: string[];
          kicad11Support:
            "preview" | "partial" | "independent" | "not-applicable";
          canarySurfaces: Array<"read" | "write" | "export">;
          fallbackPolicy: string;
          mutationGuard: string | null;
          toolCount: number;
          availableCount: number;
          blockedCount: number;
          selectedBackends: Record<string, number>;
        }
      >;
    };
    cliExports: {
      ipc2581: boolean;
      odb: boolean;
      svg: boolean;
      dxf: boolean;
      step: boolean;
      stepz?: boolean;
      xao?: boolean;
      render: boolean;
      spiceNetlist: boolean;
    };
  };
  diagnostics: string[];
}

export interface McpToolCapabilityMetadata {
  schemaVersion: string;
  name: string;
  profiles: string[];
  tier: "read" | "write" | "export" | "publish" | "human_only";
  runtime:
    "none" | "kicad_cli" | "kicad_ipc" | "ngspice" | "freerouting" | "docker";
  supports_dry_run: boolean;
  human_gate_required: boolean;
  description: string;
  verification_level: "verified" | "experimental" | "planned";
  inputSchema?: Record<string, unknown>;
  annotations?: Record<string, unknown>;
}

export interface McpToolDiscoveryResponse {
  schemaVersion?: string;
  _meta?: Record<string, unknown>;
  nextCursor?: string;
  tools: Array<{
    name: string;
    description?: string;
    inputSchema?: Record<string, unknown>;
    annotations?: Record<string, unknown>;
  }>;
  resources?: Array<{ uri?: string; name?: string; description?: string }>;
  prompts?: Array<{ name: string; description?: string }>;
  [key: string]: unknown;
}

export interface ExtensionActiveContextPayload {
  schemaVersion?: string;
  activeFile?: string | null;
  fileType: "schematic" | "pcb" | "other";
  drcErrors: string[];
  projectId?: string;
  projectName?: string;
  projectRoot?: string;
  projectFile?: string;
  selectedNet?: string;
  selectedReference?: string;
  activeVariant?: string;
  activeSheetPath?: string;
  visibleLayers?: string[];
  kicadVersion?: string;
  designBlocks?: string[];
  cursorPosition?: {
    line: number;
    character: number;
  };
  selectedArea?: {
    x1: number;
    y1: number;
    x2: number;
    y2: number;
  };
}

export interface NormalizedDiagnostic {
  schemaVersion: string;
  source: "drc" | "erc" | "syntax";
  severity: "error" | "warning" | "info";
  message: string;
  path: string;
  code?: string;
  line?: number;
  column?: number;
  reference?: string;
  net?: string;
  capturedAt: string;
}

export interface BomNetlistSummary {
  schemaVersion: string;
  project: {
    name: string;
    rootPath?: string;
    projectFile?: string;
  };
  bom: {
    totalComponents: number;
    uniqueValues: number;
    entries: Array<{
      references: string[];
      value: string;
      footprint: string;
      quantity: number;
      mpn?: string;
      manufacturer?: string;
      lcsc?: string;
      description?: string;
      dnp?: boolean;
    }>;
  };
  netlist: {
    netCount: number;
    nodes: Array<{
      netName: string;
      pins: Array<{
        reference: string;
        pin: string;
      }>;
    }>;
  };
}

export interface McpServerHealth {
  schemaVersion: string;
  server: "kicad-mcp-pro";
  version: string;
  status: "ok" | "degraded" | "error";
  mcpProtocolVersion: string;
  toolSchemaVersion: string;
  transport: {
    type: "stdio" | "streamable-http" | "sse";
    endpoint: string | null;
  };
  kicad: {
    cliFound: boolean;
    cliVersion: string | null;
    ipcAvailable: boolean;
  };
  diagnostics: string[];
}

export interface CompatibilityManifest {
  schemaVersion: string;
  products: Record<
    string,
    {
      version: string;
      supportedSchemaMajors: number[];
    }
  >;
  schemas: Record<
    string,
    {
      current: string;
      compatibility: string;
    }
  >;
  policy: {
    breakingChanges: "major";
    additiveChanges: "minor";
    documentationChanges: "patch";
  };
}

export const PROTOCOL_SCHEMA_DEFINITIONS: Readonly<
  Record<ProtocolSchemaName, ProtocolJsonSchema>
> = Object.freeze({
  "bom-netlist-summary": require("../schemas/bom-netlist-summary.schema.json"),
  "compatibility-manifest": require("../schemas/compatibility-manifest.schema.json"),
  "extension-active-context": require("../schemas/extension-active-context.schema.json"),
  "kicad-mcp-server-info": require("../schemas/kicad-mcp-server-info.schema.json"),
  "mcp-server-health": require("../schemas/mcp-server-health.schema.json"),
  "mcp-tool-capability": require("../schemas/mcp-tool-capability.schema.json"),
  "mcp-tool-discovery": require("../schemas/mcp-tool-discovery.schema.json"),
  "normalized-diagnostic": require("../schemas/normalized-diagnostic.schema.json"),
});

export class ProtocolSchemaValidator {
  private readonly ajv: Ajv2020;
  private readonly validators = new Map<ProtocolSchemaName, ValidateFunction>();

  constructor(
    private readonly schemas: Readonly<
      Record<ProtocolSchemaName, ProtocolJsonSchema>
    > = PROTOCOL_SCHEMA_DEFINITIONS,
  ) {
    this.ajv = new Ajv2020({ allErrors: true, strict: false });
    for (const schemaName of PROTOCOL_SCHEMA_NAMES) {
      const schema = this.schemas[schemaName];
      this.ajv.addSchema(schema, schema.$id);
      this.validators.set(schemaName, this.ajv.compile(schema));
    }
  }

  validate<T = unknown>(
    schemaName: ProtocolSchemaName,
    payload: unknown,
  ): ProtocolValidationResult<T> {
    const validate = this.validatorFor(schemaName);
    const schemaVersion = protocolSchemaVersion(schemaName);
    const schemaValid = Boolean(validate(payload));
    const versionError = schemaValid
      ? validatePayloadSchemaMajor(schemaName, schemaVersion, payload)
      : undefined;
    const valid = schemaValid && versionError === undefined;
    const result: ProtocolValidationResult<T> = {
      schemaName,
      schemaVersion,
      valid,
      errors: valid
        ? []
        : (versionError ?? normalizeAjvErrors(validate.errors)),
    };
    if (valid) {
      result.data = payload as T;
    }
    return result;
  }

  private validatorFor(schemaName: ProtocolSchemaName): ValidateFunction {
    const validate = this.validators.get(schemaName);
    if (!validate) {
      throw new Error(`Unknown protocol schema: ${schemaName}`);
    }
    return validate;
  }
}

let defaultValidator: ProtocolSchemaValidator | undefined;

export function getProtocolSchemaValidator(): ProtocolSchemaValidator {
  defaultValidator ??= new ProtocolSchemaValidator();
  return defaultValidator;
}

export function validateProtocolPayload<T = unknown>(
  schemaName: ProtocolSchemaName,
  payload: unknown,
): ProtocolValidationResult<T> {
  return getProtocolSchemaValidator().validate<T>(schemaName, payload);
}

export function validateMcpServerInfoContract(
  payload: unknown,
): ProtocolValidationResult<McpServerInfoContract> {
  return validateProtocolPayload<McpServerInfoContract>(
    "kicad-mcp-server-info",
    payload,
  );
}

export function isMcpServerInfoContract(
  payload: unknown,
): payload is McpServerInfoContract {
  return validateMcpServerInfoContract(payload).valid;
}

export function validateMcpToolDiscovery(
  payload: unknown,
): ProtocolValidationResult<McpToolDiscoveryResponse> {
  return validateProtocolPayload<McpToolDiscoveryResponse>(
    "mcp-tool-discovery",
    payload,
  );
}

export function validateToolCapabilityMetadata(
  payload: unknown,
): ProtocolValidationResult<McpToolCapabilityMetadata> {
  return validateProtocolPayload<McpToolCapabilityMetadata>(
    "mcp-tool-capability",
    payload,
  );
}

export function validateExtensionActiveContextPayload(
  payload: unknown,
): ProtocolValidationResult<ExtensionActiveContextPayload> {
  return validateProtocolPayload<ExtensionActiveContextPayload>(
    "extension-active-context",
    payload,
  );
}

export function validateNormalizedDiagnostic(
  payload: unknown,
): ProtocolValidationResult<NormalizedDiagnostic> {
  return validateProtocolPayload<NormalizedDiagnostic>(
    "normalized-diagnostic",
    payload,
  );
}

export function validateBomNetlistSummary(
  payload: unknown,
): ProtocolValidationResult<BomNetlistSummary> {
  return validateProtocolPayload<BomNetlistSummary>(
    "bom-netlist-summary",
    payload,
  );
}

export function validateMcpServerHealth(
  payload: unknown,
): ProtocolValidationResult<McpServerHealth> {
  return validateProtocolPayload<McpServerHealth>("mcp-server-health", payload);
}

export function validateCompatibilityManifest(
  payload: unknown,
): ProtocolValidationResult<CompatibilityManifest> {
  return validateProtocolPayload<CompatibilityManifest>(
    "compatibility-manifest",
    payload,
  );
}

export function protocolSchemasRoot(startDir = __dirname): string {
  return join(findProtocolSchemasPackageRoot(startDir), "schemas");
}

export function protocolSchemaPath(
  schemaName: ProtocolSchemaName,
  startDir = __dirname,
): string {
  return join(protocolSchemasRoot(startDir), `${schemaName}.schema.json`);
}

export function findProtocolSchemasPackageRoot(startDir = __dirname): string {
  let current = resolve(startDir);
  for (;;) {
    const packageJsonPath = join(current, "package.json");
    if (existsSync(packageJsonPath) && existsSync(join(current, "schemas"))) {
      return current;
    }
    const parent = dirname(current);
    if (parent === current) {
      throw new Error(
        `Could not find @oaslananka/kicad-protocol-schemas package root from ${startDir}`,
      );
    }
    current = parent;
  }
}

export function protocolSchemaVersion(schemaName: ProtocolSchemaName): string {
  const metadata =
    PROTOCOL_SCHEMA_DEFINITIONS[schemaName]["x-kicad-studio-kit"];
  if (isRecord(metadata) && typeof metadata["schemaVersion"] === "string") {
    return metadata["schemaVersion"];
  }
  return KICAD_PROTOCOL_SCHEMA_VERSION;
}

function normalizeAjvErrors(
  errors: ErrorObject[] | null | undefined,
): ProtocolValidationError[] {
  return (errors ?? []).map((error) => ({
    path: error.instancePath || "/",
    message: error.message ?? "schema validation failed",
    keyword: error.keyword,
  }));
}

function validatePayloadSchemaMajor(
  schemaName: ProtocolSchemaName,
  supportedVersion: string,
  payload: unknown,
): ProtocolValidationError[] | undefined {
  if (!isRecord(payload) || typeof payload["schemaVersion"] !== "string") {
    return undefined;
  }

  const payloadMajor = majorVersion(payload["schemaVersion"]);
  const supportedMajor = majorVersion(supportedVersion);
  if (payloadMajor === undefined || supportedMajor === undefined) {
    return undefined;
  }
  if (payloadMajor === supportedMajor) {
    return undefined;
  }

  return [
    {
      path: "/schemaVersion",
      message: `${schemaName} payload declares unsupported schema major ${payloadMajor}; expected ${supportedMajor}.x`,
      keyword: "schemaMajor",
    },
  ];
}

function majorVersion(version: string): number | undefined {
  const match = /^(\d+)\.\d+\.\d+$/.exec(version);
  return match ? Number(match[1]) : undefined;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}
