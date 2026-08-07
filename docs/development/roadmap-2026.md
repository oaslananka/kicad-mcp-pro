# 2026 Technical Roadmap

This roadmap converts the May 2026 research findings into enforceable repository
work. It favors small gates and measurable artifacts over large rewrites.

## August 2026 status snapshot

- Version 3.30.0 was published on 2026-08-04 for the Python/server, npm wrapper,
  and desktop GUI release surfaces; 3.30.1 followed on 2026-08-05. The release
  history and exact changes remain authoritative in `CHANGELOG.md` and GitHub
  Releases rather than being re-described here.
- [M9 — Apps UI, Hybrid Bridge & Distribution](https://github.com/oaslananka/kicad-mcp-pro/milestone/9)
  has verified progress from PR #569 plus completed #571, #572, and #575. It
  remains open for #412, #573, and #574; in particular, the read-only ChatGPT
  Apps surface must not be presented as completion of the hosted/local mutation
  or desktop release-hardening work.
- [M10 — Agent Design OS & Workflow Surface](https://github.com/oaslananka/kicad-mcp-pro/milestone/10)
  carries the post-release hardening backlog. After #579, the remaining open
  work is #576, #577, #578, and #580.
- July release-readiness closeout work is historical; current roadmap language
  should track these live milestones and objective evidence instead of treating
  completed release work as pending.

## P0: Stabilize current CI and release loops

- Keep `corepack pnpm run check:ci` green on Linux and smoke coverage green on
  macOS/Windows.
- Keep `release:check` scoped to current release sections so historical changelog
  entries do not break normal CI.
- Keep CI status checks stable across the monorepo package matrix
  PR commits.
- Require PR descriptions to include exact commands run and generated artifact
  paths for agent-authored changes.

## P1: KiCad 10 runtime validation

- Keep the Ubuntu KiCad 10 smoke workflow running against a real `kicad-cli`.
- Extend smoke artifacts to include version output, stdout, stderr and generated
  export files.
- Add optional nightly/manual KiCad 10.x compatibility jobs without making RC or
  nightly builds required for release.

## P2: API modernization and compatibility guardrails

- Enforce no new SWIG/`pcbnew` usage with `compat:check`.
- Keep CLI export paths for headless deterministic exports.
- Expand IPC diagnostics in `doctor --json` with socket/auth/retry fields.
- Add adapter boundaries before exposing new KiCad IPC features as MCP tools.

## P3: HTTP and studio bridge hardening

- Add regression tests for bearer auth, token rotation, CORS origin rejection and
  wildcard rejection.
- Add debounce/delta-sync behavior to the studio watcher before increasing the
  context payload size.
- Publish a minimal threat model for local HTTP bridge deployments.

## P4: Engineering metadata enrichment

- Add structured material/stackup resources for SI/PI/EMC tools.
- Move analysis defaults into explicit JSON resources with schemas.
- Keep generated recommendations traceable to physical inputs such as substrate,
  copper weight, trace width and current assumptions.

## Publishing surfaces

| Surface             | Purpose                          | Gate                                                   |
| ------------------- | -------------------------------- | ------------------------------------------------------ |
| PyPI                | Python package distribution      | release workflow, metadata sync, package smoke         |
| GitHub Releases     | Source release, SBOM, provenance | release-please and attestation                         |
| GHCR                | CI/runtime images                | Docker build + Trivy                                   |
| MCP registry        | MCP discovery metadata           | `metadata:check`                                       |
| Documentation site  | User and operator docs           | `properdocs build -f mkdocs.yml --strict` + link check |
| VS Code Marketplace | KiCad Studio integration         | separate extension release gate                        |

## Non-goals

- Do not add a second release automation system beside release-please.
- Do not require KiCad GUI for normal `check:ci`.
- Do not merge fallback-only fixes that should live in the canonical repository.
