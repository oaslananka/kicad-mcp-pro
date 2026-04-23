# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.4.2] - 2026-04-18

### Fixed

- Made Azure DevOps release validation resilient to expired or unavailable `SAFETY_API_KEY` credentials so `pip-audit` remains the enforced dependency gate instead of breaking the publish pipeline on auth failures.

### Changed

- Bumped project release version to `2.4.2` across package, runtime, and registry metadata for the Azure CI/CD patch cut.

## [2.4.1] - 2026-04-18

### Fixed

- Refreshed the locked `authlib` dependency to `1.7.0` on the shipped release line so the default branch and release metadata no longer surface the resolved CSRF advisory.

### Changed

- Bumped project release version to `2.4.1` across package, runtime, and registry metadata for the post-`2.4.0` security patch cut.

## [2.4.0] - 2026-04-17

### Added

- Project manifest, gate-history, design-intent, and layer-coverage MCP resources plus high-speed, bringup, DFM polish, and regression prompt workflows.
- An opt-in Prometheus `/metrics` endpoint for Streamable HTTP deployments when `KICAD_MCP_ENABLE_METRICS=true`.
- `Dockerfile.kicad10` for CI images that extract `kicad-cli` from an official KiCad 10 AppImage supplied at build time.
- `vcs_tag_release()` plus recovery-branch creation during checkpoint restore.

### Changed

- Extended schematic spatial tooling so bounding boxes now include actual pin extents, `sch_find_free_placement` can honor rectangular keepout regions, and `sch_auto_place_functional` can preserve anchored symbols while applying project-spec functional spacing.
- Expanded subcircuit template inspection output to include declared left/right pin lists for each bundled template.
- Upgraded placement scoring with critical-net Manhattan proxy metrics and thermal-hotspot proximity scoring, and hardened the headless force-directed placer with keepout-aware constraints, grid snapping, and wall-clock budgets.
- Hardened FreeRouting orchestration with a pinned Docker image default, Docker-to-JAR fallback, FreeRouting 2.x CLI flags, timeout control, DRC report output support, and structured routing telemetry.
- Extended high-speed preflight checks with critical-frequency via-stub resonance warnings, package-envelope thermal via sizing, and design-intent-driven EMC return-path continuity sweeps.
- Expanded Azure validation with a Windows unit-test job and dependency audit gates for release readiness.

### Fixed

- Added SPICE directive validation for simulation sidecar entries while keeping existing analysis directives backward compatible.
- Blocked checkpoint commits that include KiCad session scrap files such as `.kicad_pro.lock` and `~$*` artifacts.

## [2.3.2] - 2026-04-16

### Fixed

- Removed the optional `InSpice` extra dependency from published package metadata so the vulnerable transitive `diskcache` runtime dependency is no longer installed with `simulation`.
- Cleaned an accidentally tracked `.history` gitlink from benchmark fixtures and ignored future editor history folders so GitHub checkout and Pages builds no longer fail on missing submodule metadata.

### Changed

- Clarified simulation documentation to describe `ngspice` CLI as the default backend with manual `InSpice` support when users install it explicitly.

## [2.3.1] - 2026-04-16

### Changed

- Aligned the release tag with the current `main` branch after Azure CI/CD stabilization changes.
- Wired the root Azure pipeline to the shared PyPI credential group and removed the environment gate from the publish stage so automated release runs complete end-to-end.
- Kept GitHub and Azure release automation in sync for the clean patch cut.

## [2.3.0] - 2026-04-16

### Added

- KiCad 10 sidecar-backed design variants with BOM diff/export helpers.
- Time-domain routing helpers, tuning profiles, graphical DRC rule management, 3D PDF export, and manufacturing import commands.
- KiCad Studio context resource support, local HTTP bridge documentation, `.well-known` discovery metadata, and Azure DevOps pipeline definition.
- Unit/property tests and KiCad 10 benchmark fixtures for new routing, variant, design-intent, and studio flows.

### Changed

- Added inferred MCP tool annotations, progress reporting for long-running tools, and client-side sampling integration in the auto-fix loop.
- Hardened cache invalidation, path handling, release documentation, and manual GitHub fallback guidance around Azure DevOps-first CI/CD.
- Normalized project documentation and user-facing messages to consistent English wording.

### Fixed

- Removed stale TTL cache behavior across project/schematic/PCB mutations and test runs.
- Stabilized schematic move behavior to use deterministic file-based updates during automated flows.
- Aligned quality gates, router profile declarations, lint/type expectations, and release metadata for full-suite validation.

## [2.0.2] - 2026-04-14

### Fixed

- Restored complete sdist/wheel contents for package installs and `uvx` entrypoints.
- Preserved environment-based MCP client configuration unless CLI options explicitly override it.
- Preferred KiCad 10 `pcb export gerbers` and kept singular `gerber` as a fallback.
- Rejected export output traversal/absolute path writes and escaped custom symbol strings.

### Changed

- Updated Docker, registry, docs, and security metadata for the 2.x release line.

## [2.0.1] - 2026-04-13

### Added

- Project-level quality, connectivity, placement, and manufacturing release gates for agent-guided review loops.
- Design intent storage plus quality/fix-queue resources and benchmark release-gate fixtures.

### Changed

- Hard-blocked manufacturing package export when the project fails production quality gates.
- Tightened release workflows, startup diagnostics, and validation-driven agent prompts for production review flows.

## [2.0.0] - 2026-04-13

### Added

- `kicad-sch-api`-backed schematic surface with hierarchy, connectivity, and auto-placement helpers.
- FreeRouting orchestration, DSN/SES staging, and rule-file routing tools.
- Live component search, detail, BOM pricing, stock, and alternative-part lookup.
- SPICE simulation tools with InSpice-first and ngspice fallback execution.
- Signal integrity, power integrity, EMC compliance, DFM profile, HDI/multilayer, and Git checkpoint tool families.
- Focused v2 server profiles for `schematic_only`, `pcb_only`, `high_speed`, `power`, `simulation`, and `analysis`.

### Changed

- Raised the runtime baseline to Python 3.12+.
- Replaced the legacy URL-only LCSC helpers with live component search tools in one breaking API transition.
- Hardened core runtime helpers, type safety, CLI discovery, and thread-safe board access.
- Switched tool discovery to show runtime metadata labels and added pagination/filtering to large PCB read tools.
- Bumped package, runtime, and registry metadata to `2.0.0`.

## [1.0.5] - 2026-04-13

### Changed

- Bumped project release version to 1.0.5 across package/runtime/registry metadata.

## [1.0.0] - 2026-04-13

### Added

- Public distribution and CLI branding as `kicad-mcp-pro`.
- Src-based `kicad_mcp` package layout.
- Config-driven project discovery and cross-platform KiCad CLI lookup.
- MCP resources, prompts, profiles, and refactored project/PCB/schematic/export tooling.
- Packaging, CI, docs, registry metadata, and Docker assets.
