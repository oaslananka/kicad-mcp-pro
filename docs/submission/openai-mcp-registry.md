# OpenAI MCP Registry Submission

This document covers the registry publish path driven by `server.json`.

## Source of Truth

- Use the checked-in `server.json` as the generated registry payload for submission.
- Do not hand-edit generated registry payloads.
- Keep `server.json` synchronized with canonical `pyproject.toml` and `compatibility.yaml` inputs.
- Version must match `src/kicad_mcp/__init__.py`.

## Verified MCP Registry Status (2026-11-17)

The official MCP Registry API reports `io.github.oaslananka/kicad-mcp-pro`
version `4.16.0` as **active** and **latest** (`isLatest: true`).
The registry reports publication at `2026-11-15T00:09:40Z`. This is an
observation of an existing publication, **not** a publication performed by
this compatibility change.

| Field | Official latest registry record | Local `server.json` |
| --- | --- | --- |
| Status | `active`, `isLatest: true` | n/a |
| Version | `4.16.0` | `4.16.0` |
| Packages | PyPI, npm, OCI (`4.16.0`) | PyPI, npm, OCI |
| Repository | `https://github.com/oaslananka/kicad-mcp-pro` | Same canonical URL |

The historical `2.1.0` registry entry remains accessible but is no longer
the latest. Verify the `isLatest` field rather than treating the first result
from a search response as the current release.

**Published license metadata caveat:** The existing PyPI `4.16.0` distribution
reports `MIT` in PyPI JSON metadata, matching its release-time
`pyproject.toml`. Current source `LICENSE`, `pyproject.toml`, and
`server.json` use `AGPL-3.0-only`. This change does not retroactively
relicense the immutable published PyPI artifacts. Verify license metadata
on the next release before claiming package/source parity.

Verification commands:

```bash
# Listing status + version in the official registry
curl -fsS "https://registry.modelcontextprotocol.io/v0/servers?search=kicad-mcp-pro"

# Local manifest validity + publish payload (target/endpoint, no publish)
pnpm run mcp:manifest:check
pnpm run publish:mcp:dry-run
```

### Endpoint and Workflow Verification

- `publish_mcp_registry.py` defaults `MCP_REGISTRY_TARGET=official`; with no
  `MCP_REGISTRY_URL` override it delegates to the pinned `mcp-publisher` CLI, which targets
  the official registry (`registry.modelcontextprotocol.io`) by default. Endpoint confirmed
  correct.
- `.github/workflows/publish-mcp-registry.yml` `publish` job runs `mcp-publisher login github-oidc`
  then `mcp-publisher publish` from the repository root, gated to
  `release: published` or `workflow_dispatch` with `dry_run=false`.

### Update Path (for a future release)

No stored registry API token is required — the official target authenticates via GitHub
OIDC under the `oaslananka` namespace (`id-token: write`).

1. Confirm PyPI/GHCR artifacts exist for the **new** target version; `4.16.0` is already registered.
2. Trigger the publish job via a GitHub `release: published` event, or manually via
   `workflow_dispatch` with `dry_run=false`.
3. Approve the `mcp-registry` GitHub Environment when prompted (manual environment gate).
4. Re-run the `search` command above and confirm the new `isLatest` record, version and repository URL.

## Dry Run Flow

- [ ] Run `pnpm run submission:check` first.
- [ ] Run `uv run --all-extras python scripts/publish_mcp_registry.py --dry-run`.
- [ ] Inspect the dry-run payload for repository URL correctness.
- [ ] Inspect the dry-run payload for privacy URL correctness.
- [ ] Inspect the dry-run payload for package identifiers.
- [ ] Inspect the dry-run payload for transport type `stdio`.
- [ ] Stop if dry-run output contains old owner strings.
- [ ] Stop if dry-run output contains a container image outside GHCR canonical namespace.

## Live Publish Flow

- [ ] Run live publish only after dry-run output is reviewed.
- [ ] Use the maintainer account controlled by Osman Aslan.
- [ ] Record live publish UTC timestamp in [`docs/public-listing.md`](../public-listing.md).
- [ ] Record registry response URL in [`docs/public-listing.md`](../public-listing.md) only after it is public.
- [ ] Do not publish from a dirty working tree.
- [ ] Do not publish with placeholder screenshots if the registry requires production media.

## PyPI Trusted Publisher OIDC

- [ ] Confirm PyPI project name is `kicad-mcp-pro`.
- [ ] Confirm PyPI publication workflow is `publish-python.yml`.
- [ ] Confirm production PyPI environment is `pypi`.
- [ ] Confirm owner is `oaslananka`.
- [ ] Confirm repository is `kicad-mcp-pro`.
- [ ] Confirm OIDC `id-token: write` remains configured for release publish.
- [ ] Remove token-based PyPI secrets after Trusted Publishing is active.
- [ ] Do not paste PyPI credentials into registry forms or docs.

## Container Image Verification

- [ ] Image pattern: `ghcr.io/oaslananka/kicad-mcp-pro:<version>`.
- [ ] Use the version from `pyproject.toml`.
- [ ] Verify digest before announcing a release.
- [ ] Verify provenance before announcing a release.
- [ ] Do not publish DockerHub coordinates because DockerHub is not enabled.
- [ ] Do not publish old GHCR namespace coordinates.

## Cosign Verification Snippet

```bash
VERSION=$(python -c "import tomllib; print(tomllib.load(open('pyproject.toml', 'rb'))['project']['version'])")
cosign verify ghcr.io/oaslananka/kicad-mcp-pro:${VERSION} \
  --certificate-identity-regexp "https://github.com/oaslananka/kicad-mcp-pro/.github/workflows/publish-mcp-container.yml@refs/tags/mcp-server-v.*" \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com
```

## Registry Metadata Checks

- [ ] Check `server.json` schema before publish.
- [ ] Check package registry entry `kicad-mcp-pro` before publish.
- [ ] Check OCI package identifier before publish.
- [ ] Check website URL before publish.
- [ ] Check current source license value `AGPL-3.0-only` before publish.
- [ ] Check capabilities include tools.
- [ ] Check capabilities include resources.
- [ ] Check capabilities include prompts.

## Failure Handling

- [ ] If schema validation fails, fix `server.json` and rerun `metadata:check`.
- [ ] If PyPI version is missing, stop until release publication completes.
- [ ] If GHCR image is missing, stop until container publication completes.
- [ ] If cosign verification fails, treat release as blocked.
- [ ] If registry rejects metadata, open a GitHub issue with the exact rejected field.
- [ ] If network is offline, treat PyPI reachability as warning-only in local checks.

## Final Registry Publish Controls

- [ ] Confirm `server.json` remains the generated registry payload used for submission.
- [ ] Confirm `server.json` schema validation passes before dry run.
- [ ] Confirm `server.json` stays synchronized with `pyproject.toml`.
- [ ] Confirm `pyproject.toml` version matches `server.json`.
- [ ] Confirm `src/kicad_mcp/__init__.py` version matches `server.json`.
- [ ] Confirm PyPI package `kicad-mcp-pro` is reachable for the current version.
- [ ] Confirm registry package transport is `stdio`.
- [ ] Confirm registry package runtime hint is `uvx` for PyPI.
- [ ] Confirm registry package runtime hint is `docker` for OCI.
- [ ] Confirm OCI identifier includes the current version tag.
- [ ] Confirm OCI image field omits the tag where the schema expects image base.
- [ ] Confirm GHCR image namespace is `ghcr.io/oaslananka/kicad-mcp-pro`.
- [ ] Confirm old GHCR namespace values do not appear in dry-run output.
- [ ] Confirm repository URL is the canonical GitHub URL.
- [ ] Confirm website URL is the GitHub Pages URL.
- [ ] Confirm support URL is GitHub issues when the registry asks for support.
- [ ] Confirm privacy URL is the GitHub Pages privacy page when requested.
- [ ] Confirm current source license value is `AGPL-3.0-only`.
- [ ] Confirm capabilities list tools.
- [ ] Confirm capabilities list resources.
- [ ] Confirm capabilities list prompts.
- [ ] Confirm no registry payload includes local filesystem paths.
- [ ] Confirm no registry payload includes secrets or auth tokens.
- [ ] Confirm dry-run output is reviewed before live publish.
- [ ] Confirm live publish is not attempted from a dirty working tree.
- [ ] Confirm live publish is not attempted before release artifacts exist.
- [ ] Confirm live publish is not attempted when PyPI current version is missing.
- [ ] Confirm live publish is not attempted when GHCR current version is missing.
- [ ] Confirm live publish is not attempted when cosign verification fails.
- [ ] Confirm release workflow uses GitHub OIDC for PyPI Trusted Publisher.
- [ ] Confirm release workflow emits Sigstore verification material.
- [ ] Confirm release workflow emits SHA-256 checksums.
- [ ] Confirm release workflow emits CycloneDX SBOM material.
- [ ] Confirm release workflow emits GHCR provenance attestations.
- [ ] Confirm the container digest is recorded in release evidence before announcement.
- [ ] Confirm `cosign verify` command uses the current version string.
- [ ] Confirm the certificate identity regex targets this repository only.
- [ ] Confirm registry rejection responses are tracked as GitHub issues.
- [ ] Confirm registry rejection responses do not include private reviewer data.
- [ ] Confirm a corrected dry run is attached to any resubmission issue.
- [ ] Confirm `pnpm run publish:mcp:dry-run` succeeds before live publish.
- [ ] Confirm `pnpm run metadata:check` succeeds before live publish.
- [ ] Confirm `pnpm run mcp:manifest:check` succeeds before live publish.
- [ ] Confirm `pnpm run docker:metadata:check` succeeds before live publish.
- [ ] Confirm `pnpm run release:dry-run` succeeds before live publish.
- [ ] Confirm `pnpm run submission:check` succeeds before live publish.
- [ ] Confirm generated tool documentation is current before live publish.
- [ ] Confirm README public listing links are current before live publish.
- [ ] Confirm privacy policy content is current before live publish.
- [ ] Confirm release notes mention namespace migration when relevant.
- [ ] Confirm package registry names are copied from manifests, not typed manually.
- [ ] Confirm maintainer identity is Osman Aslan with handle `oaslananka`.
- [ ] Confirm publication timestamps are recorded in UTC.
- [ ] Confirm public listing URL is recorded only after it resolves externally.
- [ ] Confirm failed live publish attempts are documented with exact failing field names.
- [ ] Confirm any manual dashboard field is reviewed by a second local check command.
- [ ] Confirm the public registry entry is rechecked after cache propagation.
- [ ] Confirm post-publish metadata sync is run if manifests changed during release.
- [ ] Confirm the branch used for publish evidence has been merged into `main`.
- [ ] Confirm no temporary payload files are left in the repository after publish.
- [ ] Confirm local logs are redacted before copying into public issues.
- [ ] Confirm live publish is postponed if network reachability is unstable.
- [ ] Confirm the final outcome is reflected in [`docs/public-listing.md`](../public-listing.md).
- [ ] Confirm the next release repeats this checklist rather than copying stale evidence.
- [ ] Confirm registry docs are updated if the registry schema version changes.
- [ ] Confirm `scripts/schemas/server.schema.json` is updated only from the official schema.
- [ ] Confirm registry status from the live API; avoid marking an existing publication as not submitted.
- [ ] Confirm the submission evidence includes the exact commit SHA reviewed.
- [ ] Confirm the release tag used for registry publication is immutable.
- [ ] Confirm a rollback note exists if registry metadata must be corrected later.
- [ ] Confirm public support instructions remain GitHub-issue based.
- [ ] Confirm public documentation links do not rely on private repositories.
- [ ] Confirm the registry publish path is not confused with Anthropic or ChatGPT dashboards.
