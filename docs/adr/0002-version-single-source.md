# ADR-0002: Version Single Source

**Status:** Accepted
**Date:** 2026-05-04
**Deciders:** @oaslananka

## Context

The package exposes version metadata through Python imports, Python packaging metadata, MCP registry metadata, and server metadata. Version drift across those surfaces can mislead users, clients, release tooling, and registry automation.

## Decision

`pyproject.toml` and `src/kicad_mcp/__init__.py` are the authoritative version sources. Generated public metadata in `mcp.json` and `server.json` is synchronized by `scripts/sync_mcp_metadata.py` and checked in CI with `npm run metadata:check`.

## Consequences

- Release changes must update the Python package version and Python module version together.
- `mcp.json` and `server.json` should be treated as generated metadata surfaces, not hand-edited version authorities.
- Pull requests must fail when metadata parity drifts.

## Verification

`npm run metadata:check` exits with status 0, and `mcp.json`, `server.json`, `pyproject.toml`, and `src/kicad_mcp/__init__.py` report the same version.
