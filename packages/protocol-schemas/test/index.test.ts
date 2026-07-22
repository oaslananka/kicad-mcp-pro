import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

import {
  PROTOCOL_SCHEMA_DEFINITIONS,
  PROTOCOL_SCHEMA_NAMES,
  protocolSchemaPath,
  protocolSchemaVersion,
  validateBomNetlistSummary,
  validateCompatibilityManifest,
  validateExtensionActiveContextPayload,
  validateMcpServerHealth,
  validateMcpServerInfoContract,
  validateMcpToolDiscovery,
  validateNormalizedDiagnostic,
  validateToolCapabilityMetadata,
} from "@oaslananka/kicad-protocol-schemas";

test("exports every protocol schema definition and filesystem path", () => {
  assert.deepEqual(PROTOCOL_SCHEMA_NAMES, [
    "bom-netlist-summary",
    "compatibility-manifest",
    "extension-active-context",
    "kicad-mcp-server-info",
    "mcp-server-health",
    "mcp-tool-capability",
    "mcp-tool-discovery",
    "normalized-diagnostic",
  ]);

  for (const schemaName of PROTOCOL_SCHEMA_NAMES) {
    const schema = PROTOCOL_SCHEMA_DEFINITIONS[schemaName];
    assert.equal(
      schema.$schema,
      "https://json-schema.org/draft/2020-12/schema",
    );
    assert.equal(protocolSchemaVersion(schemaName), "1.0.0");
    assert.ok(fs.existsSync(protocolSchemaPath(schemaName)));
  }
});

test("validates server-info payloads and reports schema errors", () => {
  const valid = validateMcpServerInfoContract(serverInfoFixture());

  assert.equal(valid.valid, true);
  assert.equal(valid.data?.server, "kicad-mcp-pro");

  const current = serverInfoFixture();
  const {
    headlessIpcRequested: _headlessIpcRequested,
    headlessIpcAvailable: _headlessIpcAvailable,
    ...previousKicad
  } = current.kicad;
  const { adapterRouting: _adapterRouting, ...previousCapabilities } =
    current.capabilities;
  const previousMinor = {
    ...current,
    schemaVersion: "1.2.0",
    kicad: previousKicad,
    capabilities: previousCapabilities,
  };
  assert.equal(validateMcpServerInfoContract(previousMinor).valid, true);

  const invalid = validateMcpServerInfoContract({
    ...serverInfoFixture(),
    server: "other-server",
  });

  assert.equal(invalid.valid, false);
  assert.ok(invalid.errors.some((error) => error.path === "/server"));
});

test("rejects payloads that declare an unsupported schema major", () => {
  const invalid = validateMcpServerInfoContract({
    ...serverInfoFixture(),
    schemaVersion: "2.0.0",
  });

  assert.equal(invalid.valid, false);
  assert.deepEqual(invalid.errors, [
    {
      path: "/schemaVersion",
      message:
        "kicad-mcp-server-info payload declares unsupported schema major 2; expected 1.x",
      keyword: "schemaMajor",
    },
  ]);
});

test("validates shared protocol payload families", () => {
  assert.equal(
    validateToolCapabilityMetadata({
      schemaVersion: "1.0.0",
      name: "kicad_health",
      profiles: ["minimal", "analysis"],
      category: "project",
      tier: "read",
      runtime: "none",
      writes_files: false,
      writes_kicad_gui_state: false,
      supports_dry_run: false,
      supports_rollback: false,
      human_gate_required: false,
      requires_human_confirmation: false,
      description: "",
      verification_level: "verified",
      maturity: "stable",
      advisory_level: "none",
      tested_kicad_versions: ["10.0.x"],
    }).valid,
    true,
  );

  const toolDiscovery = validateMcpToolDiscovery({
    schemaVersion: "1.7.0",
    _meta: { "io.modelcontextprotocol/related-task": "OASLANA-52" },
    nextCursor: "next-page",
    tools: [{ name: "kicad_health", inputSchema: { type: "object" } }],
    resources: [],
    prompts: [],
    vendorExtension: { accepted: true },
  });
  assert.equal(toolDiscovery.valid, true);
  assert.equal(toolDiscovery.data?.nextCursor, "next-page");

  assert.equal(
    validateMcpToolDiscovery({
      tools: [{ name: "kicad_health", inputSchema: { type: "object" } }],
      resources: [],
      prompts: [],
    }).valid,
    true,
  );

  assert.equal(
    validateExtensionActiveContextPayload({
      schemaVersion: "1.0.0",
      activeFile: "board.kicad_pcb",
      fileType: "pcb",
      drcErrors: ["clearance"],
      cursorPosition: { line: 1, character: 2 },
    }).valid,
    true,
  );

  assert.equal(
    validateNormalizedDiagnostic({
      schemaVersion: "1.0.0",
      source: "drc",
      severity: "error",
      message: "Clearance violation",
      path: "board.kicad_pcb",
      capturedAt: "2026-05-25T00:00:00.000Z",
    }).valid,
    true,
  );

  assert.equal(
    validateBomNetlistSummary({
      schemaVersion: "1.0.0",
      project: { name: "demo" },
      bom: {
        totalComponents: 1,
        uniqueValues: 1,
        entries: [
          {
            references: ["R1"],
            value: "10k",
            footprint: "Resistor_SMD:R_0603",
            quantity: 1,
          },
        ],
      },
      netlist: {
        netCount: 1,
        nodes: [{ netName: "GND", pins: [{ reference: "R1", pin: "1" }] }],
      },
    }).valid,
    true,
  );

  assert.equal(
    validateMcpServerHealth({
      schemaVersion: "1.0.0",
      server: "kicad-mcp-pro",
      version: "3.5.2",
      status: "ok",
      mcpProtocolVersion: "2025-11-25",
      toolSchemaVersion: "1.0.0",
      transport: {
        type: "streamable-http",
        endpoint: "http://127.0.0.1:3334/mcp",
      },
      kicad: { cliFound: true, cliVersion: "KiCad 10.0.4", ipcAvailable: true },
      diagnostics: [],
    }).valid,
    true,
  );

  assert.equal(
    validateCompatibilityManifest({
      schemaVersion: "1.0.0",
      products: {
        "kicad-studio": { version: "1.0.0", supportedSchemaMajors: [1] },
        "kicad-mcp-pro": { version: "3.5.2", supportedSchemaMajors: [1] },
      },
      schemas: {
        "kicad-mcp-server-info": {
          current: "1.0.0",
          compatibility: ">=1.0.0 <2.0.0",
        },
      },
      policy: {
        breakingChanges: "major",
        additiveChanges: "minor",
        documentationChanges: "patch",
      },
    }).valid,
    true,
  );
});

function serverInfoFixture() {
  return {
    schemaVersion: "1.3.0",
    server: "kicad-mcp-pro",
    description: "KiCad MCP Pro server for PCB and schematic workflows.",
    localizedDescriptions: {
      en: "KiCad MCP Pro server for PCB and schematic workflows.",
      tr: "PCB ve sematik is akislari icin KiCad MCP Pro sunucusu.",
    },
    version: "3.5.2",
    mcpProtocolVersion: "2025-11-25",
    toolSchemaVersion: "1.0.0",
    compatibilityRange: {
      kicadStudio: {
        required: ">=3.5.2 <4.0.0",
        recommended: ">=3.5.2 <4.0.0",
        testedAgainst: "3.5.2",
      },
      kicadMcpPro: {
        required: ">=1.0.0 <2.0.0",
        testedAgainst: "1.0.0",
      },
    },
    transport: {
      type: "streamable-http",
      streamableHttp: true,
      statelessHttp: true,
      legacySse: false,
      authRequired: false,
      endpoint: "http://127.0.0.1:3334/mcp",
    },
    kicad: {
      cliFound: true,
      cliPath: "/usr/bin/kicad-cli",
      cliVersion: "KiCad 10.0.4",
      ipcAvailable: true,
      ipcVersion: "KiCad 10.0.4",
      ipcApiVersion: null,
      ipcMajorVersion: 10,
      ipcEndpointSource: "default",
      livePcbContext: true,
      liveSchematicContext: false,
      headlessIpcRequested: false,
      headlessIpcAvailable: false,
      ipcDocumentLoaded: true,
    },
    operatingMode: {
      active: "readonly",
      default: "readonly",
      available: ["readonly", "write", "manufacturing", "experimental"],
      experimentalEnabled: false,
      toolAvailability: {
        kicad_get_version: {
          available: true,
          requiredMode: "readonly",
          reason: null,
        },
        pcb_add_track: {
          available: false,
          requiredMode: "write",
          reason: "Requires write operating mode.",
        },
        export_manufacturing_package: {
          available: false,
          requiredMode: "manufacturing",
          reason: "Requires manufacturing operating mode.",
        },
        route_tune_length: {
          available: false,
          requiredMode: "experimental",
          reason: "Requires experimental operating mode.",
        },
      },
    },
    capabilities: {
      fileBackedDrc: true,
      fileBackedErc: true,
      fileBackedExports: true,
      livePcbRead: true,
      livePcbWrite: true,
      liveSchematicRead: false,
      liveSchematicWrite: false,
      liveEditingTools: {
        pcb_place_component: liveTool(9),
        pcb_route_trace: {
          available: true,
          backend: "kicad-ipc",
          reason: null,
          minimumKiCadMajor: 9,
        },
        pcb_add_zone: liveTool(9),
        pcb_set_design_rules: {
          available: true,
          backend: "hybrid-file-ipc",
          reason: null,
          minimumKiCadMajor: 9,
        },
        pcb_move_component: liveTool(9),
        pcb_delete_object: liveTool(9),
        sch_add_component: liveTool(10),
        sch_add_wire: liveTool(10),
        sch_modify_property: liveTool(10),
      },
      chatgptConnectorCompatible: false,
      adapterRouting: {
        schemaVersion: "1.0.0",
        context: {
          kicadMajor: 10,
          ipcReachable: true,
          livePcbContext: true,
          liveSchematicContext: false,
          headlessIpcAvailable: false,
          cliAvailable: true,
          ngspiceAvailable: false,
          freeroutingAvailable: false,
          dockerAvailable: true,
          networkAvailable: true,
        },
        categories: {
          pcb_read: {
            preferredBackends: ["kicad-11-headless-ipc", "kicad-gui-ipc"],
            kicad11Support: "preview",
            canarySurfaces: ["read"],
            fallbackPolicy: "Prefer IPC and fail closed for IPC-only tools.",
            mutationGuard: null,
            toolCount: 1,
            availableCount: 1,
            blockedCount: 0,
            selectedBackends: { "kicad-gui-ipc": 1 },
          },
        },
      },
      cliExports: {
        ipc2581: true,
        odb: true,
        svg: true,
        dxf: true,
        step: true,
        stepz: true,
        xao: true,
        render: true,
        spiceNetlist: true,
      },
    },
    diagnostics: [],
  };
}

function liveTool(minimumKiCadMajor: number) {
  return {
    available: true,
    backend: "kicad-ipc",
    reason: null,
    minimumKiCadMajor,
  };
}
