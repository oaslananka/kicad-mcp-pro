# Tauri Desktop Instructions

These instructions apply to `src-tauri/**` and supplement the repository root `AGENTS.md`.

## Boundary

The desktop app is a Rust/Tauri shell around the local KiCad MCP Pro backend. It owns desktop lifecycle, backend startup/health negotiation, loopback UI connectivity, Tauri capabilities, and desktop packaging. It must not become an alternate implementation of server policy.

Read first:

- `ARCHITECTURE.md`
- `docs/security/threat-model.md`
- `docs/development/release-process.md`
- `src-tauri/tauri.conf.json`
- `src-tauri/src/lib.rs`

## Backend compatibility

The desktop/backend compatibility handshake is a release contract.

Preserve:

- exact release-version policy where currently required;
- the desktop API contract version;
- health-check validation before treating an existing service as compatible;
- explicit failure for a different/incompatible service already bound to the port;
- exact backend package selection for release builds.

Do not silently fall forward/backward to a different Python release merely because `uvx` can resolve one.

## Local service and CSP boundary

The desktop UI/backend relationship is intentionally local.

- Keep backend bind/connect assumptions on loopback unless security policy is intentionally redesigned.
- Do not broaden CSP `connect-src` or local service exposure for convenience.
- Treat shell/dialog/plugin capability changes as security-sensitive.
- Do not turn an unavailable or incompatible backend into an implicit remote/fallback service.

## Process lifecycle

- Preserve child-process cleanup on app shutdown.
- Keep health/startup timeouts bounded and consistent with the frontend/backend startup contract.
- Avoid blind restart loops when startup may still be in progress.
- Do not leak tokens, sensitive environment data, or private project contents into desktop logs.
- User-selected working directories remain untrusted filesystem input and must not bypass server path policy.

## Version and release parity

Desktop version changes must remain synchronized with the repository release/version policy and relevant Python/package metadata. Do not bump `Cargo.toml` or `tauri.conf.json` in isolation when the release process expects cross-surface parity.

Generated icons/bundles are outputs; use repository-owned generation/build commands.

## Verification

For Rust/Tauri changes run focused tests plus:

```bash
cargo check --manifest-path src-tauri/Cargo.toml
task pre-push
```

For user-visible desktop changes use the applicable web/desktop smoke path. For packaging/release changes use the release/GUI workflows or dry-run checks required by repository policy.

## Definition of done

A desktop change is complete only when backend compatibility, loopback/CSP security, lifecycle, capabilities, version parity, tests, and packaging behavior remain aligned.
