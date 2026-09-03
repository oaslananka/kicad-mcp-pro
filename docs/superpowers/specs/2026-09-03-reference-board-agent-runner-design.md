# Reference-board agent runner design

## Purpose

Issue #730 needs serious PCB attempts produced from written specifications with complete, sanitized attempt history. The existing `pcb-reference-board.v1` bundle validator and `pcb-task-outcome.v1` KPI schema remain authoritative; this work adds only an execution and evidence-capture harness.

## Execution boundary

The runner invokes Claude Code non-interactively with one explicit KiCad MCP configuration. It uses `--strict-mcp-config`, excludes user settings with `--setting-sources project`, supplies an empty explicit settings file, and exposes only `ToolSearch` plus `mcp__kicad__*` tools. Built-in shell, file-editing, web, and unrelated MCP tools are unavailable to the benchmark agent.

The reviewed phase profiles are `build` + `write` for schematic and PCB phases, and `release` + `manufacturing` for manufacturing. Each phase points KiCad MCP at an attempt workspace and an explicit KiCad 10 CLI path. PCB-live operations require the reviewed GUI-connected IPC precondition rather than silently falling back to an unverified target.

## Evidence boundary

Claude stream-json is temporary runner input, never publication evidence. The sanitizer retains only timestamps, stable MCP tool names, start/completion/failure status, primary/auxiliary model identifiers, permission-denial count, session outcome, and bounded scalar metadata. Prompts, tool arguments, tool results, reasoning, provider text, environment values, credentials, absolute unrelated paths, and raw model responses are never copied into `agent-log.jsonl`.

Every run produces a deterministic `ReferenceAgentRunSummary` used to construct the existing `AttemptRecord`. Failed provider/tool runs remain attempts; the runner must not delete or hide them.
