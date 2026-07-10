# Roadmap

KiCad MCP Pro follows a monthly minor release cadence. This document tracks
upcoming milestones and records what was delivered in completed cycles.

Dates are targets, not promises. Breaking changes follow the RFC process
described in `GOVERNANCE.md`.

---

## Current Release Line

The authoritative version lives in `pyproject.toml` / `src/kicad_mcp/__init__.py`;
each release records a version-pinned evidence snapshot in a dated
`docs/release-readiness-<date>.md` document. This section is kept
version-agnostic so it does not drift.

- Package metadata is synchronized across `pyproject.toml`, `package.json`,
  `server.json`, `src/kicad_mcp/__init__.py`, and README on every release.
- Public packages are verified for each release line on PyPI and npm.
- GHCR `ghcr.io/oaslananka/kicad-mcp-pro:<version>` is published as a multi-arch
  OCI index per release.
- KiCad 10.0.4 remains the primary stable KiCad baseline.
- MCP protocol compatibility remains aligned with the 2025-11-25 schema used by
  `server.json` and the generated tool contracts.

---

## Completed Milestones

### ✅ 3.1 (Delivered)
- Hardened GitHub supply-chain: Renovate, CodeQL, Gitleaks, Scorecard, SBOM,
  Sigstore, artifact attestations.
- Expanded cross-platform CI for Windows and macOS unit smoke tests.

### ✅ 3.2 (Delivered)
- Deeper property-based tests for SI, PI, thermal, project discovery helpers.
- Mutation-testing baselines established.
- Docs expanded: troubleshooting, API stability, benchmark fixture contribution.

### ✅ 3.3 – 3.5 (Delivered)
- KiCad 10 primary target and KiCad 10.x feature-parity work.
- Multi-arch container publishing (GHCR).
- OpenTelemetry observability and structured logging lifecycle.
- Operating modes: readonly / write / manufacturing / experimental.
- MCP protocol 2025-11-25 compliance.
- Doctor diagnostics and redacted support bundles.

### ✅ 3.6 (Delivered — 2026-05-27)
- KiCad IPC capability gating.
- Localization infrastructure (i18n).
- STEPZ and XAO export formats.
- Streamable HTTP as primary transport; SSE deprecated and disabled by default.
- Compatibility matrix for the KiCad 10.0.x baseline.

### ✅ 3.7.x (Delivered — 2026-06-03 to 2026-06-05)
- Initial migration from kicad-studio-kit monorepo.
- Protocol-schemas as public npm package.
- Scorecard workflow hardened; Gitleaks pre-commit hook added.

### ✅ 3.8.0 (Delivered — 2026-06-06)
- Phase 2 CLI-parity tools: 20+ footprint, symbol, jobset, upgrade, board import.
- 3D render formats: BREP, GLB, GenCAD, IPC-D356, PLY, STL, U3D, VRML, PS.
- Schematic export expansion: DXF, SVG, PS, python_bom, sch_upgrade.
- Path traversal hardening across new CLI-backed tools.
- KiCad 9.x deprecation process prepared for the 3.9 removal window.

### ✅ 3.9.x – 3.16.x (Delivered)
- KiCad 9.x removal completed and compatibility metadata moved to dropped-state
  policy.
- KiCad 10.0.4 compatibility and canary documents added.
- Agent integrations, setup/doctor workflows, toolset profiles, generated tool
  references, and parity-regression checks expanded.
- Release hardening, OpenSSF Silver evidence, repository maturity reports, and
  public-listing submission packs added.
- Manufacturing, routing, library, schematic safety, SI/PI/EMC/thermal, and
  validation surfaces received incremental coverage and honesty gates.

---

## Upcoming

### 3.18 (Target: July 2026)
- **Release-readiness closeout:** keep PyPI, npm, GHCR, GitHub Releases,
  `server.json`, README, and docs synchronized before external submissions.
- **Public listing readiness:** keep production screenshots, demo media, privacy,
  support, registry metadata, and reviewer prompts submission-ready.
- **KiCad 10.0.4 evidence refresh:** re-run and archive CLI canary evidence for
  the current release line.
- **Scorecard evidence refresh:** verify branch ruleset, release evidence, and
  accepted solo-maintainer exceptions after workflow-name changes.

### 3.19 (Target: Q3 2026)
- **Structured verdicts:** finish stable machine-readable PASS/WARN/FAIL payloads
  across high-traffic gates.
- **Schematic write safety:** migrate remaining mutating schematic writers to the
  guarded round-trip layer or explicit unsupported-path behavior.
- **Capability parity gaps:** close bitmap/board-art import and define the
  solver-grade analysis contract.

### 4.0 (Target: TBD — RFC required)
- Remove APIs that have completed their documented deprecation window.
- Revisit profile names and tool grouping through the RFC process.
- Keep KiCad 10.x as the sole stable primary path until KiCad 11 has enough
  headless-IPC evidence to become primary.
- Evaluate Python 3.14 as the minimum supported version once the ecosystem and
  package consumers are ready.

---

## Ownership

Current maintainer: `@oaslananka`. Larger API or workflow changes go through
the RFC process described in `GOVERNANCE.md`.
