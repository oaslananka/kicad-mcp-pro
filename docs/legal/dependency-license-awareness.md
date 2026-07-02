# Dependency license awareness

KiCad MCP Pro is distributed under the MIT license. Third-party packages are tracked through manifests and lockfiles.

## Policy

- Keep the root LICENSE as the project license source of truth.
- Review dependency updates for license changes when Renovate opens update PRs.
- Do not vendor external code unless source, version, license, update procedure, and reason are documented.
- Add a NOTICE file only if an asset or dependency requires attribution beyond the MIT license file.

## Current evidence

| Area | Evidence |
| --- | --- |
| Project license | LICENSE, pyproject.toml, package metadata |
| Python packages | pyproject.toml, uv.lock |
| JavaScript packages | package.json, pnpm-lock.yaml |
| Rust packages | Cargo manifests and lockfiles where present |
| Dependency updates | renovate.json with vulnerability alerts and lockfile maintenance |
| Dependency security audit | scripts/audit_dependencies.py and security:audit |

## REUSE posture

The repository is not currently claiming full REUSE compliance. A future pass should run in report-only mode first, then become enforced only after a file-level policy is agreed.

## Release evidence

When consumers need a formal dependency license report, generate it as release evidence next to SBOM, checksum, and provenance artifacts.
