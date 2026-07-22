# FAQ

## Which MCP client should I use?

Use the client that already fits your workflow. VS Code, Cursor, Claude Desktop, Claude Code, Codex, and generic MCP clients are documented in the client configuration guide.

## Is KiCad 10 required?

<!-- public-metadata:kicad-support:start -->
KiCad 10.0.x is the primary supported target. KiCad 8.x remains deprecated and is limited to file-level read and migration support. KiCad 9.x has been dropped and is not supported. KiCad 11.x is preview-only. The executable support policy lives in `compatibility.yaml`.
<!-- public-metadata:kicad-support:end -->

## Why does the server need a project directory?

Project-scoped paths let the server keep writes inside the active KiCad project, generate outputs predictably, and avoid accidental edits outside the board workspace.

## Why are there profiles?

Profiles reduce the tool surface for agents. `pcb_only`, `schematic_only`, `manufacturing`, `analysis`, and `agent_full` help clients expose only the tools needed for a workflow.

## Is telemetry enabled?

No. Telemetry is disabled by default. Operators can explicitly opt in to
OpenTelemetry by setting `OTEL_EXPORTER_OTLP_ENDPOINT` or passing `--telemetry`;
the exported attributes are operational only and intentionally omit project
paths, design contents, request arguments, CLI output, and collector headers.

## Where should I ask questions?

Use GitHub Discussions for usage questions and ideas. Use issues for reproducible bugs, regressions, and documentation defects.
