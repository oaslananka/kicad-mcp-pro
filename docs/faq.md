# FAQ

## Which MCP client should I use?

Use the client that already fits your workflow. VS Code, Cursor, Claude Desktop, Claude Code, Codex, and generic MCP clients are documented in the client configuration guide.

## Is KiCad 10 required?

KiCad 10 is the primary target. KiCad 9 is supported on a best-effort basis for core PCB, schematic, validation, and export workflows. KiCad 10-only features are called out in the KiCad 10 docs.

## Why does the server need a project directory?

Project-scoped paths let the server keep writes inside the active KiCad project, generate outputs predictably, and avoid accidental edits outside the board workspace.

## Why are there profiles?

Profiles reduce the tool surface for agents. `pcb_only`, `schematic_only`, `manufacturing`, `analysis`, and `agent_full` help clients expose only the tools needed for a workflow.

## Is telemetry enabled?

No. Telemetry is not collected by default. If opt-in anonymous telemetry is added later, it must be explicit, documented, and disabled by default.

## Where should I ask questions?

Use GitHub Discussions for usage questions and ideas. Use issues for reproducible bugs, regressions, and documentation defects.
