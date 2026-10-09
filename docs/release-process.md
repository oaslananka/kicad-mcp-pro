# Release Process

Releases use Conventional Commits and release-please as the canonical release PR
and changelog mechanism. Release Drafter is not used.

Release preparation (`.github/workflows/release-please.yml`) and publication
(`.github/workflows/publish-release.yml`) use short-lived, repository-scoped
GitHub App installation tokens. No long-lived personal access token is required.
The preparation workflow runs daily at 03:37 UTC or by explicit workflow dispatch.
Neither preparation path creates a release tag or publishes a package.

## Normal Release

1. Confirm the release PR's required CI, security, CodeQL, SonarCloud,
   documentation and release-readiness checks are green.
2. Review and merge the protected release-please PR. This updates version
   metadata on `main` but **does not** create tags, GitHub Releases or packages.
3. When publication is explicitly authorized, use **Actions → Publish Release →
   Run workflow**, select `main` and run it. This is the only normal
   release-creation action; there are no version input fields or extra
   environment approval prompts.
4. Confirm `Publish Release` created the expected release tags and GitHub
   Releases. The resulting tag/release events start package-specific workflows;
   verify their protected environments, source tags and required gates.
5. Verify PyPI/npm publication, version and digest parity, SBOMs, checksums,
   artifact attestations and registry provenance applicable to each artifact.
6. Confirm docs are available from the canonical `gh-pages` branch at
   `https://oaslananka.github.io/kicad-mcp-pro/`.
7. Post a short GitHub Discussions announcement when appropriate.

## Release Workflow

Release-please derives versions from Conventional Commits and
`.release-please-manifest.json`. The daily preparation workflow creates or
updates a release PR with synchronized version-derived files, with
`skip-github-release: true`.

Only the maintainer-triggered **Publish Release** workflow runs on `main`
with `skip-github-pull-request: true` and `skip-github-release: false`.
Its output tags and GitHub Releases trigger distinct Python, npm, GUI,
container and other package workflows with their own source verification,
build, provenance, signature, evidence and publication requirements. GitHub
Release assets can arrive **after** the release event; do not treat a newly
created release as proof that all package-specific publishers finished.

Do not create tags manually or use individual `publish-*` workflow dispatches
as an alternative to the normal maintainer publication decision. Existing
backfill/recovery dispatches require a separately authorized recovery operation.

## Hotfix

Use `hotfix/<issue>` for urgent security, data loss, or production blocking fixes. Cherry-pick to a maintained release branch only when that branch exists and has users.

## Version Metadata

Run this before release PR review if metadata changes are manual:

```bash
pnpm run metadata:sync
pnpm run metadata:check
```

`pyproject.toml` is canonical for package version and repository identity, while `compatibility.yaml` is canonical for runtime support policy. `server.json` and the marked public documentation blocks are generated surfaces.
