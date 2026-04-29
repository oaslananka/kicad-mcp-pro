# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [3.1.5](https://github.com/oaslananka-lab/kicad-mcp-pro/compare/v3.1.4...v3.1.5) (2026-04-29)


### Bug Fixes

* align kicad studio http docs publishing ([935210a](https://github.com/oaslananka-lab/kicad-mcp-pro/commit/935210ac0ad871085daa9e20e9b48b929b07e653))

## [3.1.4] - 2026-04-29

### Fixed

- Published the CLI diagnostics surface with `health`, `doctor`, `serve`, and
  `version` commands so `uvx kicad-mcp-pro health --json` and
  `uvx kicad-mcp-pro doctor --json` work from the released package.

## [3.1.3](https://github.com/oaslananka-lab/kicad-mcp-pro/compare/v3.1.2...v3.1.3) (2026-04-29)


### Bug Fixes

* keep task install non-admin on windows ([3b020cf](https://github.com/oaslananka-lab/kicad-mcp-pro/commit/3b020cf55e866e32e74c2834a580d5b8c36b0ae8))
* keep task install non-admin on windows ([9d4b7b4](https://github.com/oaslananka-lab/kicad-mcp-pro/commit/9d4b7b426815f67983d219d852597eaef6554bd8))

## [3.1.2](https://github.com/oaslananka-lab/kicad-mcp-pro/compare/v3.1.1...v3.1.2) (2026-04-29)


### Bug Fixes

* break codeql import cycles ([#23](https://github.com/oaslananka-lab/kicad-mcp-pro/issues/23)) ([2319dae](https://github.com/oaslananka-lab/kicad-mcp-pro/commit/2319daea64e4254419c87917bd78aa9fbcb2602f))
* install workflow lint tool in release ([#22](https://github.com/oaslananka-lab/kicad-mcp-pro/issues/22)) ([be85674](https://github.com/oaslananka-lab/kicad-mcp-pro/commit/be8567489c540338ff2c2572d9474eb83316bca9))
* satisfy codeql export compatibility aliases ([#24](https://github.com/oaslananka-lab/kicad-mcp-pro/issues/24)) ([d3be55b](https://github.com/oaslananka-lab/kicad-mcp-pro/commit/d3be55b42ffe35f1d249acc75195efeb65b66bb9))
* use pypi-compatible license metadata ([f0db726](https://github.com/oaslananka-lab/kicad-mcp-pro/commit/f0db7269c97a305116858e8bce2b7db490ad8dda))
* use pypi-compatible license metadata ([735f1a3](https://github.com/oaslananka-lab/kicad-mcp-pro/commit/735f1a34e3e57cb1c583ce4457bd700fef66ac85))

## [3.1.1](https://github.com/oaslananka-lab/kicad-mcp-pro/compare/v3.1.0...v3.1.1) (2026-04-28)


### Bug Fixes

* allow release-please service token ([#20](https://github.com/oaslananka-lab/kicad-mcp-pro/issues/20)) ([8ea4dc3](https://github.com/oaslananka-lab/kicad-mcp-pro/commit/8ea4dc3cf747431685b1faa8ebbe17c1d091922b))
* unblock release publish token verification ([#19](https://github.com/oaslananka-lab/kicad-mcp-pro/issues/19)) ([4ce8aac](https://github.com/oaslananka-lab/kicad-mcp-pro/commit/4ce8aac55cd6d36074a3aa547e6097b3361ac0d3))

## [3.1.0](https://github.com/oaslananka-lab/kicad-mcp-pro/compare/v3.0.2...v3.1.0) (2026-04-28)


### Features

* harden cli diagnostics and maintenance gates ([6b5c135](https://github.com/oaslananka-lab/kicad-mcp-pro/commit/6b5c135696a3f353ec8d606a48ea6fb64931ba7d))


### Bug Fixes

* clean code scanning warnings ([0dbb9bf](https://github.com/oaslananka-lab/kicad-mcp-pro/commit/0dbb9bfdbd98fe7ac37c415031a61e4d5522342d))
* harden canonical mirror sync ([c357e47](https://github.com/oaslananka-lab/kicad-mcp-pro/commit/c357e47bf6f148042f3b328aaf31abcfb02dda42))
* make doppler secret verifier Windows-safe ([c615df7](https://github.com/oaslananka-lab/kicad-mcp-pro/commit/c615df7e449f79cd97cdc7b634f15ca6d8ec0285))
* quote label colors ([fff7812](https://github.com/oaslananka-lab/kicad-mcp-pro/commit/fff7812658d142e6230642edc70230e64630d45d))
* reduce code scanning noise ([3b8a05a](https://github.com/oaslananka-lab/kicad-mcp-pro/commit/3b8a05ab8b300c5e8664a2c18448e0e50aaae698))
* remove kicad session import cycle ([dcbfc92](https://github.com/oaslananka-lab/kicad-mcp-pro/commit/dcbfc924bbb8e9b9d98074b6b29947189b858104))
* skip canonical remote sentinel during sync ([2541641](https://github.com/oaslananka-lab/kicad-mcp-pro/commit/2541641f0a8d76998efbb5eb4615d13f0220dffe))
* stabilize code scanning cleanup ([97c30e3](https://github.com/oaslananka-lab/kicad-mcp-pro/commit/97c30e34d933a1fc33e2b72580a1b48df18f6501))

## [Unreleased]

## [3.0.2] - 2026-04-27

### Fixed

- Fixed Claude Code `stdio` startup races by deferring heavy tool/resource registration
  until after the MCP `initialize` handshake can bind.
- Added an e2e regression test that sends `initialize` immediately after process spawn.

### Changed

- Bumped project release version to 3.0.2 across package/runtime/registry metadata.

## [3.0.1] - 2026-04-27

### Added

- Added HTTP token rotation, per-tool metrics, request audit logging, heavy-tool rate limiting, and expanded server-card capability negotiation.
- Added explicit variant selection for gated manufacturing package export.
- Added `project_generate_design_prompt()` and AC PDN impedance estimates for `check_power_integrity()`.
- Added release-hardening tests for profile discovery, fixer imports, gate-history migrations, watcher locking, CLI retry behavior, structured errors, metadata linting, and benchmark latency.

### Changed

- Bumped project release version to 3.0.1 across package/runtime/registry metadata.
- Tool execution failures now return MCP `isError` results with structured `error_code`, `message`, and `hint` content for capable clients.
- Published tool descriptions are normalized to meet metadata lint requirements.
- Deprecated `tune_track_length()` now emits a `UserWarning` in addition to the existing structured log warning.

### Fixed

- Fixed discovery gaps for validation CLI tools and the `builder`, `critic`, and `release_manager` profile surface.
- Fixed `_SyncServerHandle.list_tools()` returning a coroutine when called inside an active event loop.
- Fixed studio watch auto-detection overriding an explicitly configured project directory.
- Added `PRAGMA user_version` schema versioning for gate-history SQLite databases.

## [3.0.0] - 2026-04-26

### Added

- Added `sch_add_missing_junctions()` plus automatic T-intersection junction insertion for generated schematic wiring.
- Added `project_full_validation_loop()` for bounded ERC/DRC/quality-gate fix iteration and `project_gate_trend()` for persisted gate history inspection.
- Added `professional_circuit_design` and `post_placement_routing` prompts to make agent workflows deterministic from schematic capture through routing.
- Added a grid-based schematic A* router, a lightweight PDN mesh solver, project-local gate-history persistence, and ten new YAML subcircuit blueprints.

### Changed

- `pcb_sync_from_schematic()` now has backward-compatible `force` and `auto_place` options, blocks unsafe syncs behind a pre-sync gate by default, and can run force-directed placement after successful sync.
- Schematic wire writes now deduplicate duplicate segments and merge collinear runs before persisting.
- Schematic routing now avoids symbol bodies with A*/Z-route fallback instead of blindly drawing L-routes through obstacles.
- Placement and routing prompts now include post-placement DSN export, FreeRouting, SES import, zone refill, and DRC steps.
- `pcb_place_decoupling_caps()` now applies value-specific proximity rules for common bypass and bulk capacitors.
- Bumped project release version to 3.0.0 across package/runtime/registry metadata.

### Fixed

- Fixed missing junctions on T-intersections that could make visually connected schematic wires absent from the netlist.
- Fixed pre-sync PCB transfer behavior so ERC/connectivity/annotation failures are blocked unless explicitly forced.

## [2.4.8] - 2026-04-26

### Changed

- Bumped project release version to 2.4.8 across package/runtime/registry metadata.

## [2.4.7] - 2026-04-26

### Changed

- Bumped project release version to 2.4.7 across package/runtime/registry metadata.

## [2.4.6] - 2026-04-26

### Changed

- Bumped project release version to 2.4.6 across package/runtime/registry metadata.

## [2.4.5] - 2026-04-26

### Changed

- Bumped project release version to 2.4.5 across package/runtime/registry metadata.

## [2.4.4] - 2026-04-26

### Changed

- Bumped project release version to 2.4.4 across package/runtime/registry metadata.

## [2.4.3] - 2026-04-26

### Changed

- Bumped project release version to 2.4.3 across package/runtime/registry metadata.

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
