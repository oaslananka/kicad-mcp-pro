# Release asset immutability inventory

This page maps every workflow step that creates a GitHub Release or adds,
replaces or deletes release assets. It is the working record for upstream issue
**#1179** ("release: finalize assets before enabling immutable GitHub
Releases"). It also describes the ratchet that stops new post-publication
mutations from landing while the migration is pending.

!!! warning "Scope of this page"
    The repository immutability setting is not changed by this work. No tag,
    release or publish workflow was triggered to produce this inventory. The
    tables below come from static review of `.github/workflows/*.yml` and
    `release-please-config.json`, and from the deterministic
    `scripts/check_release_asset_mutations.py` inventory. They are not live
    release evidence.

## Why the current flow is incompatible with immutable releases

GitHub immutable releases lock a release's assets and tag once the release is
published. Assets can only be added while the release is still a **draft**.
Today the repository publishes first and attaches assets afterwards:

1. CI calls `publish-release.yml` after a reviewed Release Please merge. Its
   `Publish merged Release Please versions` step runs
   `googleapis/release-please-action` with `skip-github-release: false`.
   `release-please-config.json` sets no `draft` option, so Release Please
   creates the tag **and a published, non-draft GitHub Release** for each
   released component before any asset exists.
2. The tag push and the `release: published` event then start the per-family
   publishers.
3. Each publisher builds, attests and verifies its artifacts and runs
   `gh release upload ... --clobber` against the **already published**
   release. `--clobber` replaces any existing asset with the same name.

With immutability enabled, step 3 would fail for every family. A publisher
that re-ran (recovery or backfill) would also be rejected, because it relies
on `--clobber` to overwrite assets.

## Release families

Tag prefixes come from `release-please-config.json`. Release Please links the
versions of `mcp-server`, `mcp-npm` and `kicad-mcp-gui` (`linked-versions`
plugin). `protocol-schemas` is versioned on its own.

| Family | Tag prefix | Release created by | Publisher workflows and trigger |
| --- | --- | --- | --- |
| MCP server (Python, MCPB, KiCad PCM, container, MCP Registry) | `mcp-server-v` | `publish-release.yml` (Release Please) | `publish-python.yml` (`push: tags mcp-server-v*`); `publish-mcpb.yml`, `publish-kicad-pcm.yml`, `publish-mcp-container.yml`, `publish-mcp-registry.yml`, `release.yml` (`release: published`); each also has `workflow_dispatch` recovery |
| npm launcher | `mcp-npm-v` | `publish-release.yml` (Release Please) | `publish-npm.yml` (`release: published`, `workflow_dispatch` backfill) |
| Protocol schemas | `protocol-schemas-v` | `publish-release.yml` (Release Please) | `publish-protocol-schemas.yml` (`release: published`, `workflow_dispatch` backfill) |
| Desktop GUI | `kicad-mcp-gui-v` | `publish-release.yml` (Release Please), **or** `gui-release.yml` if the release does not exist yet | `gui-release.yml` (`push: tags kicad-mcp-gui-v*`, `workflow_dispatch`) |

The `release: published` workflows are started by the Release Please run
because it uses the release-automation GitHub App token, not `GITHUB_TOKEN`.

## Asset and mutation map

Line numbers refer to the workflow files at the time of writing. The ratchet
keys entries by workflow, job and step name, not by line number.

| Workflow : job | Step | Required assets | Command (line) | Timing relative to publication | `--clobber` | Registry or digest verification | Mutates a published release |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `publish-release.yml` : `publish` | Publish merged Release Please versions | none (creates tags and releases) | `googleapis/release-please-action`, `skip-github-release: false` (111-118) | creates the published release | n/a | n/a | **yes** (creates non-draft releases) |
| `publish-python.yml` : `build` | Attach Python evidence to GitHub Release | wheel, sdist, `kicad-mcp-pro-python-SHA256SUMS.txt`, `kicad-mcp-pro-python-sbom.cdx.json`, `kicad-mcp-pro-python-release-evidence.json` | `gh release upload ... --clobber` (80-105; waits up to 18 x 10 s for the release; `push` events only) | after publication; before TestPyPI/PyPI publish | yes | `verify-pypi` and `verify-pypi-provenance` (153-165, 220-235); `actions/attest` (62-64) | **yes** |
| `publish-npm.yml` : `publish` | Attach npm evidence to GitHub Release | launcher `.tgz`, `mcp-npm-SHA256SUMS.txt`, `mcp-npm-sbom.cdx.json` | `gh release upload ... --clobber` (115-126) | after publication; before `npm publish` | yes | `isDraft == false` source check (59); `actions/attest` (102-104) | **yes** |
| `publish-npm.yml` : `publish` | Attach npm post-publish verification to GitHub Release | `npm-published-digest.json` | `gh release upload ... --clobber` (154-158) | after publication **and** after `npm publish` (140) | yes | `scripts/verify-npm-release.mjs` (144-153) | **yes** |
| `publish-mcpb.yml` : `publish` | Attach MCPB bundle and evidence to GitHub Release | `kicad-mcp-pro-<version>.mcpb`, `kicad-mcp-pro-mcpb-SHA256SUMS.txt`, `kicad-mcp-pro-mcpb-release-evidence.json` | `gh release upload ... --clobber` (178-186) | after publication | yes | `targetCommitish` source check (86); `actions/attest` (164-166) | **yes** |
| `publish-protocol-schemas.yml` : `publish` | Attach evidence to GitHub Release | schemas `.tgz`, `protocol-schemas-SHA256SUMS.txt`, `protocol-schemas-sbom.cdx.json` | `gh release upload ... --clobber` (111-122) | after publication; before `npm publish` (141) | yes | `isDraft == false` source check (59); `scripts/verify-npm-release.mjs` (144-153); `actions/attest` (99-100) | **yes** |
| `publish-kicad-pcm.yml` : `publish` | Attach KiCad PCM package and evidence to GitHub Release | `kicad-mcp-pro-pcm-<version>.zip`, `kicad-mcp-pro-pcm-SHA256SUMS.txt`, PCM evidence | `gh release upload ... --clobber` (114-122) | after publication | yes | downloads the published zip and checks SHA256SUMS (124-150); `actions/attest` (100-102) | **yes** |
| `gui-release.yml` : `create-release` | Prepare release inventory | none (creates the release) | `gh release create --verify-tag --generate-notes` when `gh release view` fails (161-163) | races with `publish-release.yml` | n/a | tag commit equals source commit (151-159) | **yes** (creates a non-draft release) |
| `gui-release.yml` : `create-release` | Upload installers and evidence to GitHub Release | `.deb`, `.rpm`, `.AppImage`, `.dmg`, `.msi`, `.exe` installers, GUI SHA256SUMS, SBOM and release evidence | `gh release upload ... --clobber` (229-238) | after publication | yes | `verify-local` before (216-220); `verify-published` after download (240-253); `actions/attest` (222-227) | **yes** |

Workflows that read a release but do not change it:

- `publish-npm.yml`, `publish-protocol-schemas.yml`, `publish-mcp-container.yml`
  and `publish-mcp-registry.yml` check `isDraft == false` with `gh release view`.
- `publish-mcpb.yml` and `publish-kicad-pcm.yml` read `targetCommitish`.
- `gui-release.yml` (`Verify published GUI release inventory`) and
  `publish-kicad-pcm.yml` (`Verify published PCM digest`) run
  `gh release download --clobber`. Here `--clobber` only overwrites local files.
- `publish-mcp-container.yml` publishes to GHCR and signs the image digest
  with cosign. `publish-mcp-registry.yml` publishes `server.json` to the MCP
  Registry. Neither attaches release assets.
- `release.yml` runs release validation only.
- `release-please.yml` runs Release Please with `skip-github-release: true`.
  It prepares the release PR only and creates no release.

## Ratchet: `scripts/check_release_asset_mutations.py`

The checker loads every workflow and walks each job's steps in order. It
records each step that:

- runs `gh release create`, `upload`, `edit`, `delete` or `delete-asset`;
- runs `gh api` with a write method (`POST`, `PATCH`, `PUT`, `DELETE`, or
  implied by `-f`/`-F`/`--input`) on a `releases` path;
- runs `curl` against `uploads.github.com`, or with a write method on a
  `/releases` path;
- uses `googleapis/release-please-action` without
  `skip-github-release: true`, `softprops/action-gh-release` or
  `ncipollo/release-action`.

A command targets a **draft** only when the same job has created the release
with `--draft` (or `draft: true`) earlier and has not published it yet. Every
command is checked in order, including repeated commands in the same step.
The draft window stays open for uploads, asset deletions and `gh release edit`
calls that keep the draft. It closes on `gh release edit --draft=<value>` for
any value other than `true` or `1` (including `$VAR` and `${{ ... }}`), and on
any other write whose effect on the draft is not known, such as a `gh api` or
`curl` write (for example `-f draft=false`). Everything else is treated as
targeting a **published** release (fail closed).

Each published-release mutation must match an entry in the
`release_asset_mutations` list in `.github/actions-policy.json`. The match key
is workflow, job, step, kind and whether `--clobber` is used. Every entry must
cite a tracking issue (currently `#1179`) and give a reason. An entry covers
exactly one matching command unless it sets `count`. The check fails when:

- a new step mutates a published release without an entry;
- an existing step changes its kind or its `--clobber` flag;
- an allowlisted step gains or loses a matching command (the match count
  differs from `count`, default 1);
- an entry no longer matches any step (stale). Remove the entry when a step is
  migrated, so the list can only shrink.

The checker runs inside `scripts/check_github_actions_policy.py`, so
`pnpm run workflows:policy`, `pnpm run workflows:security`, the CI workflow
policy job and `scripts/hook_pre_push.py` all enforce it. Run it on its own
with:

```bash
uv run python scripts/check_release_asset_mutations.py
uv run python scripts/check_release_asset_mutations.py --json  # full inventory
```

Before splitting a `run` script into commands, the checker replaces GitHub
`${{ ... }}` expressions and innermost `$(...)` or backtick substitutions with
placeholders, and checks the substituted commands on their own. It also skips
`env`, `sudo`, `xargs`, `nohup`, `nice` and `timeout` prefixes, their leading
`-` options with any separate option value (`nice -n 10`, `sudo -u bot`), and
the `timeout` duration.

Known limits: the checker parses shell text. Review these cases by hand:

- It does not follow `eval`, variables that hold `gh`, shell functions, or
  helper scripts that call the GitHub API.
- Wrapper options that take a separate value (such as `xargs -I {}` or
  `env -u NAME`) are not understood, so the command after them is missed.
- Commands are matched by kind and count, not by their full text. Changing the
  arguments of an allowlisted command (for example the asset list) is not
  flagged.
- Draft inference is limited to a same-job draft create with a known
  **literal tag**. Only following operations that use the exact same tag
  qualify as draft writes; dynamic expressions, unrelated tags, unknown
  API writes, Release Please multi-family creates, and cross-job uploads
  never inherit the draft state. The checker reads a repository-contained
  Release Please manifest for initial creation classification only when all
  produced releases are demonstrably draft and immediately tagged.

The check is a ratchet, not a proof.

## Draft inventory prepublication gate (implemented, not yet wired)

The script scripts/check_draft_release_inventory.py provides a **read-only,
fail-closed** acceptance primitive for #1179. It does not create or publish
releases and **does not make the current published-first workflows compatible**
with immutable Releases. It is invoked by tests and explicit read-only checks
only.

The future orchestrator must produce a trusted inventory manifest from its
approved build outputs, pin that manifest's SHA-256 **outside the draft asset
directory**, attach the files to a draft without clobbering, download all draft
assets, and independently retrieve the draft's JSON and the protected tag's
dereferenced commit SHA. For example:

~~~bash
python -m scripts.check_draft_release_inventory manifest \
  --assets-dir assembled-assets --tag "$TAG" \
  --source-commit "$SOURCE_SHA" --output /tmp/release-manifest.json
# Capture the printed manifest_sha256 into a trusted, immutable CI output.
gh api "repos/$REPO/releases/$RELEASE_ID" > /tmp/release.json
# Download each authenticated draft asset by .assets[].id into downloaded-assets.
# Validate names before writing; tag-based download may exclude drafts.
TAG_SHA="$(git rev-parse "refs/tags/$TAG^{commit}")"
python -m scripts.check_draft_release_inventory verify \
  --assets-dir downloaded-assets \
  --manifest /tmp/release-manifest.json \
  --manifest-sha256 "$TRUSTED_MANIFEST_SHA256" \
  --release-json /tmp/release.json --repo "$REPO" --tag "$TAG" \
  --source-commit "$SOURCE_SHA" --tag-commit "$TAG_SHA"
~~~

The verifier rejects non-draft/previously published releases, wrong repository,
tag or source commit, missing/extra/duplicate assets, symlinks, empty assets,
changed sizes, and mismatched SHA-256 values. When GitHub supplies an asset
digest, that must match too. A completed verification **does not itself
authorize publication**: the caller still needs reviewed release provenance,
approved registries, per-family tests and attestations, and a trusted
single-writer publish transaction. Workflow and tag identities must come
from protected CI inputs, not a PR-provided string. A published v4.4.0
Release was tested and correctly rejected; a locally synthesized draft
snapshot of those same nine GUI assets passed. **No real draft publication
acceptance is claimed.**

## Partial draft retry planner (implemented, not yet wired)

The read-only script scripts/plan_draft_release_retry.py handles interrupted
draft uploads without assuming that retries are safe. It requires a reviewed,
independently pinned manifest from scripts.check_draft_release_inventory,
a protected tag SHA, a real draft release's JSON, the complete approved
build outputs and **freshly downloaded copies of every existing draft asset**.

Invoke from the repository root with python -m scripts.plan_draft_release_retry.
Inputs: --approved-assets, --downloaded-existing, --manifest,
--manifest-sha256, --release-json, --repo, --tag, --source-commit,
and --tag-commit. The command returns a machine-readable
list of preserveExisting and uploadMissingOnly. It never uploads, deletes,
replaces or publishes an asset.

If any existing asset differs from the protected manifest, is not downloaded,
has an invalid GitHub state/digest, or belongs to a published/foreign release,
the planner **fails closed**. Approved local build outputs must also match
the pinned manifest exactly; a nondeterministic retry build cannot silently
replace an existing release asset. A complete draft returns
readyForFinalInventoryCheck: true but still requires the final inventory
verifier, registry verification, attestations, and explicit publish authority.

The planner was tested on an offline synthetic partial-draft representation
of v4.4.0 GUI: the matching macOS DMG was preserved and eight missing files
were listed without any write; the actual published release was rejected.
**No real draft lifecycle or repository immutability acceptance is claimed.**

## Proposed draft-first orchestration (design only)

The design below covers the remaining acceptance criteria of #1179. It is not
implemented. No workflow YAML was changed for it, and every assumption marked
*unverified* must be checked against the pinned action and current GitHub
documentation before migration.

1. **Draft creation.** `publish-release.yml` keeps Release Please as the only
   release creator but sets `"draft": true` in `release-please-config.json`.
   Release Please does not push a tag for a draft release by default. The
   pinned `googleapis/release-please-action@45996ed1…` must therefore also
   support `force-tag-creation` (verified in the upstream schema), or the tag must be created by
   a separate, reviewed step at the same commit. Tags stay protected by
   `.github/rulesets/release-tags.json`.
2. **Attach to the draft.** Each family becomes a reusable workflow
   (`workflow_call`) that takes the tag and release id. It builds, attests and
   verifies its artifacts, then attaches them to the draft with
   `gh release upload` **without** `--clobber`. A name collision then fails
   loudly instead of silently replacing evidence.
3. **Registry ordering.** PyPI, npm, GHCR and the MCP Registry are published
   before the GitHub Release leaves draft, or are gated on the asset inventory
   check. Post-publication evidence that cannot exist before the registry
   upload, such as `npm-published-digest.json` from `publish-npm.yml`, moves
   to `actions/attest` attestations and workflow artifacts, or is computed
   before the draft is published.
4. **Inventory verification.** A final job in `publish-release.yml` downloads
   the draft's assets and checks them against each family's expected list and
   SHA256SUMS. The checks reuse the existing `verify-local` and
   `verify-published` helpers.
5. **Publish.** Only after verification does the job run
   `gh release edit <tag> --draft=false`. The release is then complete and
   immutable.
6. **Remove races and re-point consumers.** The `gh release create` fallback
   in `gui-release.yml` is removed. Draft releases do not emit
   `release: published`, and with draft creation the tag push may move to the
   publish step (*unverified*). So `push: tags` and `release: published`
   publishers become `workflow_call` callees of `publish-release.yml`, and only
   consumers that read a finished release keep listening to
   `release: published`.
7. **Recovery and backfill.** Recovery never clobbers a published asset. A
   failed draft is deleted and rebuilt. A published release that is missing
   assets is superseded by a new patch release instead of being edited.

**Ratchet during migration.** The checker does not yet understand this design,
so migrating a family is not just a matter of deleting allowlist entries:

- The Release Please create step now reads its checked-in manifest config.
  Classification is draft-only when each release-producing package declares
  or inherits BOTH draft=true and force-tag-creation=true. Missing, invalid,
  dynamic, escaped or symlinked-outside configuration is treated as published.
  The production config still does not enable either setting, so its legacy
  release-creation mutation remains allowlisted.

- A `workflow_call` callee that attaches to a draft made by its caller is
  classified as targeting a published release, because draft state is tracked
  only within one job. A compliant upload without `--clobber` is reported as a
  new mutation, and the old `clobber: true` entry is reported as stale.

The first migration tranche now supports tag-safe Release Please
draft classification, but deliberately does NOT exempt generic callee
uploads to drafts created in a different job or workflow. Such uploads still
look published without a verified protected release ID, explicit source/tag
identity, independent inventory checks and single-writer orchestration. A
future reviewed target contract must prove all of those preconditions before
any production allowlist entries can be retired. Any draft asset upload using
the clobber option is rejected by this ratchet even within a single job.

Once a declared-draft mechanism exists, delete each family's old
entry when it migrates. The ratchet reports an entry as stale until then.

The upstream Release Please manifest documentation explicitly supports
both draft and force-tag-creation for safe tag creation. This is static
classification only, not a live release lifecycle test:
https://github.com/googleapis/release-please/blob/main/docs/manifest-releaser.md

The production publisher and all nine legacy post-publication mutation
allowlist entries are unchanged. No releases, tags or registry artifacts were
created or modified.

## Non-goals

- The repository immutability setting is not changed by this work. Enabling it
  is a separate maintainer action, after every allowlist entry is retired.
- No tag, release or publish workflow is triggered to produce or verify this
  inventory.
- No claim is made that the draft-first design has been exercised. That
  requires live release evidence from a real release run.

## Existing-draft asset staging (experimental; no production wiring)

The new script scripts/stage_draft_release_assets.py is a narrowly scoped
staging coordinator for **an already-created draft**. It is **not** integrated
with the current publishers. It never creates a tag or Release, changes Release
metadata, or publishes a draft.

Default execution is **read-only**:

1. Validate an independently SHA-256-pinned approved manifest against local
   build outputs, plus repository, numeric Release ID and reviewed source SHA.
2. Retrieve the exact draft by numeric ID via authenticated GitHub API; dereference
   lightweight/annotated tag refs and verify that the tag points to the source.
3. Download each existing asset through its numeric GitHub asset ID into a fresh
   temporary directory and verify name, state, size and SHA-256 against the pin.
4. Report the exact preserveExisting and uploadMissingOnly lists. If nothing
   is missing, run the full prepublication inventory acceptance gate.

Example, using an **isolated existing test draft**, not an existing published
production Release:

~~~bash
uv run python -m scripts.check_draft_release_inventory manifest \
  --assets-dir "$APPROVED_ASSETS" --tag "$TEST_TAG" \
  --source-commit "$REVIEWED_SOURCE_SHA" --output "$PINNED_MANIFEST"
# Pin the printed manifest SHA-256 independently in a trusted CI output.
uv run python -m scripts.stage_draft_release_assets \
  --repo "$REPO" --release-id "$EXISTING_DRAFT_RELEASE_ID" \
  --tag "$TEST_TAG" --source-commit "$REVIEWED_SOURCE_SHA" \
  --approved-assets "$APPROVED_ASSETS" --manifest "$PINNED_MANIFEST" \
  --manifest-sha256 "$TRUSTED_MANIFEST_SHA256"
~~~

After **human-reviewed evidence, exclusive per-release orchestration and
explicit operator authorization**, the same command can be invoked with
--execute-uploads plus --confirm-repository and --confirm-release-id matching
the exact repo and numeric ID. This separately rechecks draft identity and
existing assets, uploads only missing approved files through the authenticated **numeric
release-ID asset upload API** (no tag lookup or asset replacement), downloads them independently and applies the full
prepublication inventory verifier. A failed/partial upload leaves the Release
a draft, so an authorized retry must revalidate the pinned artifacts.

GitHub operations are **not atomic** with concurrent publication. Production
callers must hold an exclusive per-release lock and prevent other publishers
from modifying the draft. This tool has **no publication mode**. A separate
reviewed finalization step must verify all family-specific registry evidence,
attestations and the draft-to-published transition before it is wired into
production. The existing nine allowlisted postpublication mutations in seven
workflows remain. These additions alone do **not** justify enabling immutable
Releases.

## Owner-run identity preflight for cross-workflow drafts (read-only)

`scripts/check_draft_release_owner.py` adds an offline-testable,
**read-only** GitHub API identity boundary for the proposed owner-driven
orchestrator. It is not connected to production publishing and has no write
flag. It accepts a numeric Release ID, protected tag and reviewed source
commit, plus an expected owner workflow run ID, retry attempt and main SHA.
It independently reads the GitHub Actions run, the Release by numeric ID,
and the protected tag ref (including annotated-tag dereference). The
owner run main commit must be the **same commit** as the approved tag target;
a merely active unrelated workflow run cannot adopt an old draft. It rejects
foreign repositories, PR/fork/other workflow origins, stale run attempts,
non-main or completed owner runs, published Releases, and changed tags.
Only an **active manual dispatch of `publish-release.yml` on main** can
qualify; current production release dispatches and workflows are unchanged.

**Identity is not a lock.** A validated owner run could still race with
another writer or a late publication. The result intentionally reports
`exclusiveWriterVerified: false` and `publicationAuthorized: false`.
Do not promote this output to a write authority, use it as an exception in
`check_release_asset_mutations.py`, or retire any of the nine legacy
entries. An eventual single owner workflow must serialize the *entire*
draft-to-publish lifecycle, with the same protected concurrency domain
for all owner-triggered writes; callees must be invoked synchronously
under that run and must recheck live draft identity immediately before
uploads. Avoid starting independent writers or attempting an unsafe
`--clobber` recovery. GitHub's Actions concurrency settings are not
independently attested by the Release or workflow-run REST responses.

Reference: https://docs.github.com/en/rest/actions/workflow-runs
and https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency

## Exact stable release-family inventory gate (implemented; not wired)

The read-only family gate validates mandatory asset **roles**, rather than
allowing an otherwise internally consistent manifest to omit an entire
producer family. Supported stable tags are mcp-server-v*, mcp-npm-v*,
protocol-schemas-v* and kicad-mcp-gui-v* with exact numeric semver.
The approved manifest must be SHA-256-pinned **outside its artifact folder**
by a trusted owner job, and must bind the protected tag and source commit.

The reviewed roles match workflow outputs and the published v4.4.0 release
inventory observed on 2026-10-25. The protocol-schemas list derives from
its workflow; no protocol-schemas-v4.4.0 GitHub Release was present.
Missing, duplicate, cross-version, malformed or extra assets are rejected.
Prerelease names and future format changes require explicit review.

Usage (read-only):

    python -m scripts.check_release_family_inventory \
      --manifest "$MANIFEST" --manifest-sha256 "$OWNER_PIN" \
      --tag "$TAG" --source-commit "$SOURCE_SHA"

This gate only verifies role coverage **inside the manifest**. Its JSON
explicitly denies live draft asset integrity, registry verification, signed
attestations, exclusive writer locks and permission to publish. The future
owner must separately run the authenticated draft-byte inventory verifier,
check all attestation and registry evidence, and establish serialized writer
authority before any final publication. No existing workflow is automatically
rewired and the nine allowlisted legacy mutations are unchanged.
