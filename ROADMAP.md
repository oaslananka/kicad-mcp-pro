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
<!-- public-metadata:runtime-policy:start -->
- Primary KiCad line: `10.0.x`; latest verified patch: `10.0.5`.
- Deprecated KiCad lines: `8.x`.
- Dropped KiCad lines: `9.x`.
- Preview KiCad lines: `11.x`.
- MCP protocol contract: `2025-11-25`.
<!-- public-metadata:runtime-policy:end -->

---

## Completed Milestones

### ✅ 3.1 (Delivered)
- Hardened GitHub supply-chain: automated dependency updates, CodeQL, Gitleaks, Scorecard, SBOM,
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

### ✅ 3.17.x – 3.30.1 (Delivered through 2026-08-05)
- The 3.30.0 release was published on 2026-08-04 across the
  [Python/server](https://github.com/oaslananka/kicad-mcp-pro/releases/tag/mcp-server-v3.30.0),
  [npm](https://github.com/oaslananka/kicad-mcp-pro/releases/tag/mcp-npm-v3.30.0), and
  [desktop GUI](https://github.com/oaslananka/kicad-mcp-pro/releases/tag/kicad-mcp-gui-v3.30.0)
  surfaces after the live-model evaluation and safety-gate hardening cycle.
- The 3.30.1 maintenance release followed on 2026-08-05 and includes the
  verified public-safe read-only ChatGPT Apps surface from
  [PR #569](https://github.com/oaslananka/kicad-mcp-pro/pull/569).
- PR #569 materially advances M9, but it does not complete the remaining hosted
  deployment, desktop provenance, or desktop/backend compatibility work tracked
  by the open M9 issues.

---

## Upcoming

### M9 — Apps UI, Hybrid Bridge & Distribution
- The [M9 milestone](https://github.com/oaslananka/kicad-mcp-pro/milestone/9)
  remains open for objective distribution and trust-boundary evidence.
- Reproducible Tauri builds (#571), updater trust-path cleanup (#572), and the
  bridge coroutine regression (#575) are complete; PR #569 verified the
  supported public-safe read-only ChatGPT Apps surface.
- Remaining work is tracked by #412 (hosted deployment and directory-readiness
  evidence), #573 (desktop installer integrity/provenance release evidence), and
  #574 (an explicit desktop-to-backend compatibility contract). The implementation
  for #573 is merged in PR #586, but the issue remains open until its required
  release-candidate evidence is recorded.

### M10 — Agent Design OS & Workflow Surface
- The [M10 milestone](https://github.com/oaslananka/kicad-mcp-pro/milestone/10)
  is now the active governance and maintainability hardening backlog.
- After this roadmap refresh (#579), the open set is #576 (one dependency-update
  source of truth), #577 (incremental composition-root decomposition), #578
  (OpenSSF Signed-Releases reconciliation), and #580 (public Best Practices badge
  submission).
- These are hardening and governance tasks; their presence does not imply that
  unfinished controls or future capabilities have shipped.

### Q3 2026 Productization
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
