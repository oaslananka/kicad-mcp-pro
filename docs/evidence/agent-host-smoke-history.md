# Agent host compatibility — dated historical evidence

This is an **index of already-recorded tests**, not a claim of current host
qualification. A static parse or MCP SDK client test must not be promoted to a
native agent installation/tool-execution pass. Evidence remains tied to its
original product commit, host version, KiCad patch and environment.

| Host | Historical observed result | Scope of evidence | Not established by this record |
| --- | --- | --- | --- |
| Claude Code `2.1.238` | Native `claude mcp add/get` against local loopback, reported `Status: Connected`; server recorded MCP initialization | KiCad `10.0.5`, secondary physical Linux host, temporary HOME and project, [source record](kicad-pcm/2026-08-29/linux-kicad-10.0.5.md) | Current Claude versions, extension/Skill installation, newly added tools, or write-mode execution |
| Codex CLI `0.150.1` | Native MCP initialize/list and **actual read-only `kicad_get_version` tool call** after #813 fix | KiCad `10.0.5`, HTTP MCP, SHA `546227bcb13eb851913eaf6d6d8d95c9a5ae367c`, merged as `a197e7ff18a18c484531b9be8c4d02a3eb762ea7`, [source record](kicad-pcm/2026-08-29/linux-kicad-10.0.5.md) | Current Codex builds, Gemini extension, Agent Skill discovery, or other transport/version combinations |
| Cursor | Project-scoped generated configuration preview/write/backup/restore preserved other entries | Disposable physical-host filesystem transaction, [source record](kicad-pcm/2026-08-29/linux-kicad-10.0.5.md) | Any actual Cursor binary connection, tool enumeration or call |

## Current host verification process

The separate [distribution readiness matrix](../status/distribution-readiness.md)
keeps these historical results discoverable. The new client compatibility
catalog (introduced by PR #1218) intentionally starts with `smokeStatus:
not-run` for **current release/host/version claims**: this does not erase older
physical evidence. Do not set a host to `passed` without a new exact-build,
platform-specific native installation + readonly-tool smoke, independently
reviewed. Tracked in [#1219](https://github.com/oaslananka/kicad-mcp-pro/issues/1219).

The KiCad 10.0.5 physical-host results were captured under their own source
conditions and are not a substitute for KiCad 10.0.7 qualification (#1181).
