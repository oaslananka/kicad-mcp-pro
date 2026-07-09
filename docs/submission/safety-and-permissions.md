# Safety and Permissions Statement

This statement is the formal safety answer for public directory reviewers.

## Summary

- KiCad MCP Pro is a local MCP server for KiCad workflows.
- Default transport is stdio.
- The server does not require a hosted backend.
- Telemetry is disabled by default; OpenTelemetry export requires explicit operator configuration.
- The server does not phone home.
- The server does not store user data remotely.

## Filesystem Scope

- [ ] Allowed scope is the selected KiCad project directory.
- [ ] Allowed scope is additionally constrained by `KICAD_MCP_WORKSPACE_ROOT` when set.
- [ ] `path_safety.py` enforces safe path handling.
- [ ] Path traversal outside workspace root must be rejected.
- [ ] Reviewer tests should use `tests/fixtures/benchmark_projects/pass_sensor_node/demo.kicad_pro`.
- [ ] Private board files are not required for review.
- [ ] Read-only inspections should not write to project files.
- [ ] Destructive operations require explicit tool calls and metadata annotations.
- [ ] Manufacturing package export is gated by project quality checks.
- [ ] Output directories should be separate from source fixtures when possible.

## Subprocess Surface

- [ ] Required subprocess: `kicad-cli`.
- [ ] Optional subprocess surface: Freerouting through Docker when configured.
- [ ] No shell command execution tool is exposed as a general MCP capability.
- [ ] KiCad CLI path may be configured through `KICAD_CLI_PATH`.
- [ ] Health checks can run when KiCad IPC is unavailable.
- [ ] IPC-dependent tools report unavailable state instead of crashing.
- [ ] Docker-based Freerouting is opt-in.
- [ ] Reviewers can skip optional integrations for directory review.

## Network and Telemetry

- [ ] Default stdio mode opens no network listener.
- [ ] Default stdio mode has no server network egress requirement.
- [ ] HTTP mode is optional.
- [ ] HTTP mode requires bearer auth for production use.
- [ ] HTTP mode requires explicit CORS allowlist for production use.
- [ ] Wildcard CORS is not an acceptable production configuration.
- [ ] No cookies are set by the local stdio server.
- [ ] No IP addresses are collected by the local stdio server.
- [ ] Usage telemetry is disabled by default and optional OpenTelemetry export is explicit.
- [ ] Optional third-party integrations follow their own privacy policies.

## Reproducible Builds

- [ ] PyPI Trusted Publisher is the intended package publish path.
- [ ] GitHub OIDC is used for trusted release identity.
- [ ] Sigstore signatures are required release evidence.
- [ ] GHCR provenance attestations are required release evidence.
- [ ] CycloneDX SBOM is required release evidence.
- [ ] SHA-256 checksums are required release evidence.
- [ ] Release workflow is protected by a `release` environment.
- [ ] Docs workflow publishes to `https://oaslananka.github.io/kicad-mcp-pro`.

## Independent Verification Commands

```bash
pnpm run metadata:check
pnpm run mcp:manifest:check
pnpm run assets:icons:check
pnpm run submission:check
pnpm run docs:tools:check
uv run --all-extras properdocs build -f mkdocs.yml --strict
```

## Container Verification Commands

```bash
VERSION=$(python -c "import tomllib; print(tomllib.load(open('pyproject.toml', 'rb'))['project']['version'])")
cosign verify ghcr.io/oaslananka/kicad-mcp-pro:${VERSION} \
  --certificate-identity-regexp "https://github.com/oaslananka/kicad-mcp-pro/.github/workflows/publish-mcp-container.yml@refs/tags/mcp-server-v.*" \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com
```

## Reviewer Safety Assertions

- [ ] A reviewer can run health checks without KiCad running.
- [ ] A reviewer can run fixture quality gates without private data.
- [ ] A reviewer can inspect tool annotations in `src/kicad_mcp/tools/metadata.py`.
- [ ] A reviewer can inspect privacy guarantees in `docs/privacy.md`.
- [ ] A reviewer can inspect threat model details in `docs/security/threat-model.md`.
- [ ] A reviewer can inspect release integrity details in `docs/security/release-integrity.md`.
- [ ] A reviewer can inspect Docker behavior in `docs/deployment/docker.md`.
- [ ] A reviewer can inspect HTTP mode behavior in `docs/deployment/http-mode.md`.

## Denied Content

- [ ] Do not include `.env` content in submissions.
- [ ] Do not include bearer token values in submissions.
- [ ] Do not include API key values in submissions.
- [ ] Do not include OAuth secret values in submissions.
- [ ] Do not include auth cookie values in submissions.
- [ ] Do not include private key files in submissions.
- [ ] Do not include customer board files in submissions.
- [ ] Do not include private screenshots with local usernames.

## Final Safety Review Controls

- [ ] Confirm stdio mode is described as local-only.
- [ ] Confirm the server itself is described as not collecting telemetry.
- [ ] Confirm the server itself is described as not storing remote user data.
- [ ] Confirm the server itself is described as not setting cookies.
- [ ] Confirm the server itself is described as not collecting IP addresses.
- [ ] Confirm filesystem scope references the selected project directory.
- [ ] Confirm filesystem scope references `KICAD_MCP_WORKSPACE_ROOT` when set.
- [ ] Confirm path traversal is described as rejected by `path_safety.py`.
- [ ] Confirm read-only inspection tools are distinguished from write tools.
- [ ] Confirm destructive tools require explicit user intent through MCP calls.
- [ ] Confirm manufacturing package export is described as quality-gated.
- [ ] Confirm `kicad-cli` is the required subprocess surface.
- [ ] Confirm Docker/Freerouting is described as optional and opt-in.
- [ ] Confirm no general shell execution capability is claimed or exposed.
- [ ] Confirm HTTP mode is described separately from local stdio mode.
- [ ] Confirm HTTP mode production notes mention bearer authentication.
- [ ] Confirm HTTP mode production notes mention explicit CORS allowlists.
- [ ] Confirm optional Nexar usage is described as third-party governed.
- [ ] Confirm optional third-party integrations are not described as default behavior.
- [ ] Confirm no reviewer evidence includes `.env` content.
- [ ] Confirm no reviewer evidence includes bearer token values.
- [ ] Confirm no reviewer evidence includes API key values.
- [ ] Confirm no reviewer evidence includes OAuth client secrets.
- [ ] Confirm no reviewer evidence includes auth cookies.
- [ ] Confirm no reviewer evidence includes private key files.
- [ ] Confirm no reviewer evidence includes customer board files.
- [ ] Confirm no screenshots include local usernames or private paths.
- [ ] Confirm release evidence references PyPI Trusted Publisher.
- [ ] Confirm release evidence references GitHub OIDC.
- [ ] Confirm release evidence references Sigstore signing.
- [ ] Confirm release evidence references GHCR provenance.
- [ ] Confirm release evidence references CycloneDX SBOM output.
- [ ] Confirm release evidence references SHA-256 checksums.
- [ ] Confirm reviewers can run `pnpm run submission:check` independently.
- [ ] Confirm reviewers can run `pnpm run mcp:manifest:check` independently.
- [ ] Confirm reviewers can run `pnpm run docs:tools:check` independently.
- [ ] Confirm reviewers can inspect `docs/privacy.md` for data handling.
- [ ] Confirm reviewers can inspect `docs/security/threat-model.md` for trust boundaries.
- [ ] Confirm reviewers can inspect `docs/security/release-integrity.md` for provenance.
- [ ] Confirm reviewers can inspect `docs/deployment/docker.md` for container behavior.
- [ ] Confirm reviewers can inspect `docs/deployment/http-mode.md` for remote mode behavior.
- [ ] Confirm reviewer fixture instructions avoid private project files.
- [ ] Confirm wrong-path failures are documented as client setup errors.
- [ ] Confirm safety language is not diluted by marketing claims.
- [ ] Confirm safety language does not promise controls not implemented in code.
- [ ] Confirm every optional integration is explicitly named as optional.
- [ ] Confirm production deployment notes do not weaken local stdio guarantees.
- [ ] Confirm post-review fixes update this statement and the privacy page together.
- [ ] Confirm final submission uses the exact current version and commit SHA.
- [ ] Confirm the current repository state is clean before safety evidence is captured.
