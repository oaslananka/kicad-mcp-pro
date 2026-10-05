# Package Boundary Instructions

These instructions apply to `packages/**` and supplement the repository root `AGENTS.md`.

## Boundary

`packages/` contains distinct distributable/test surfaces with different contracts. Do not treat them as one generic Node workspace.

Current package roles include:

- `mcp-npm/` — npm launcher/wrapper for the Python distribution;
- `protocol-schemas/` — versioned public protocol schemas and TypeScript validators;
- `kicad-fixtures/` — deterministic shared KiCad fixture corpus and expected outputs;
- `kicad-plugin/` — KiCad companion plugin code that runs inside KiCad.

Read each package's manifest/README and the repository release/compatibility policy before changes.

## npm wrapper

The npm package is a thin launcher, not a second server implementation.

- Preserve argv forwarding and child exit/signal semantics.
- Do not execute through a shell or interpolate user-controlled arguments into shell text.
- Do not silently install a mismatched Python version; package/release parity and the documented override semantics remain explicit.
- Publishing the npm wrapper must not precede the compatible Python package it launches.

## Protocol schemas

Schema changes are public compatibility changes.

- Preserve schema versioning and backward-compatibility policy.
- Update validators, tests, changelog, and generated/consuming surfaces together.
- Do not loosen validation merely to accept an implementation drift.
- Keep tool-effect and cross-product protocol contracts synchronized with canonical server metadata.

Use the package's own `pnpm run check` for protocol-schema changes.

## KiCad fixtures

Fixture data is deterministic test evidence, not arbitrary sample content.

- Keep manifest entries, fixture files, and expected outputs synchronized.
- Do not replace failing expected evidence merely to make a test pass without understanding the behavior change.
- Do not add customer/private design data, credentials, or proprietary manufacturing outputs.
- Version-sensitive fixture expectations should state or encode their supported KiCad contract.

## KiCad companion plugin

The companion plugin executes inside KiCad's Python environment.

- Keep plugin discovery failure-contained; optional plugin failure must not break unrelated KiCad plugin discovery.
- Preserve loopback-only/server-mediated behavior and safe-apply confirmation for mutation paths.
- Do not use the companion plugin to bypass server operating modes, path safety, or human manufacturing controls.
- KiCad-bundled Python/runtime constraints differ from the server environment; avoid assuming server-only dependencies are available.

## Version and release discipline

Package versions and metadata follow repository release policy; do not bump one public release surface in isolation when synchronization is required.

Lockfile changes must correspond to intentional dependency changes. Generated build output is not a substitute for source/schema updates.

## Verification

Run the narrow package command first, then repository gates selected by the change:

- `packages/protocol-schemas`: `pnpm --dir packages/protocol-schemas run check`
- `packages/kicad-fixtures`: use its local `check` script when the package toolchain is installed
- `packages/mcp-npm`: `npm --prefix packages/mcp-npm run check` and its build smoke where applicable
- cross-package/release changes: `task pre-push` and the repository package/release checks

## Definition of done

A package change is complete only when its source, manifest/version, lockfile, tests, public contract, release ordering, and consuming surfaces remain consistent.
