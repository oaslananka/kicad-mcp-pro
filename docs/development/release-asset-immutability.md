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
2. The `release: published` event then starts the per-family
   publishers.
3. Each active publisher builds, attests and verifies its artifacts, then
   attaches missing assets to the already published release. The reviewed
   shared helper verifies existing target asset bytes and IDs before writing,
   never replaces an asset, and independently verifies completed uploads.

With immutability enabled, step 3 still fails whenever an asset is missing.
The former --clobber recovery behavior is removed from active upload steps;
a conflicting rebuilt artifact must not replace published bytes.

## Release families

Tag prefixes come from `release-please-config.json`. Release Please links the
versions of `mcp-server` and `mcp-npm` (`linked-versions`
plugin). `protocol-schemas` is versioned on its own.

| Family | Tag prefix | Release created by | Publisher workflows and trigger |
| --- | --- | --- | --- |
| MCP server (Python, MCPB, KiCad PCM, container, MCP Registry) | `mcp-server-v` | `publish-release.yml` (Release Please) | `publish-python.yml`, `publish-mcpb.yml`, `publish-kicad-pcm.yml`, `publish-mcp-container.yml`, `publish-mcp-registry.yml`, `release.yml` (`release: published`); other publishers also have `workflow_dispatch` recovery; Python manual main dispatch is TestPyPI only |
| npm launcher | `mcp-npm-v` | `publish-release.yml` (Release Please) | `publish-npm.yml` (`release: published`, `workflow_dispatch` backfill) |
| Protocol schemas | `protocol-schemas-v` | `publish-release.yml` (Release Please) | `publish-protocol-schemas.yml` (`release: published`, `workflow_dispatch` backfill) |
| Desktop GUI (retired; historical) | `kicad-mcp-gui-v` | Historical Release Please / `gui-release.yml` | Retired Tauri workflow; no active publisher |

The `release: published` workflows are started by the Release Please run
because it uses the release-automation GitHub App token, not `GITHUB_TOKEN`.

## Asset and mutation map

Line numbers refer to the workflow files at the time of writing. The ratchet
keys entries by workflow, job and step name, not by line number.

| Workflow : job | Step | Required assets | Command (line) | Timing relative to publication | `--clobber` | Registry or digest verification | Mutates a published release |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `publish-release.yml` : `publish` | Publish merged Release Please versions | none (creates tags and releases) | `googleapis/release-please-action`, `skip-github-release: false` (111-118) | creates the published release | n/a | n/a | **yes** (creates non-draft releases) |
| `publish-python.yml` : `build` | Attach Python evidence to GitHub Release | wheel, sdist, `kicad-mcp-pro-python-SHA256SUMS.txt`, `kicad-mcp-pro-python-sbom.cdx.json`, `kicad-mcp-pro-python-release-evidence.json` | `scripts.attach_published_release_assets --execute` | after publication; before TestPyPI/PyPI publish | no | `verify-pypi` and `verify-pypi-provenance` (153-165, 220-235); `actions/attest` (62-64) | **yes** |
| `publish-npm.yml` : `publish` | Attach npm evidence to GitHub Release | launcher `.tgz`, `mcp-npm-SHA256SUMS.txt`, `mcp-npm-sbom.cdx.json` | `scripts.attach_published_release_assets --execute` | after publication; before `npm publish` | no | `isDraft == false` source check (59); `actions/attest` (102-104) | **yes** |
| `publish-npm.yml` : `publish` | Attach npm post-publish verification to GitHub Release | `npm-published-digest.json` | `scripts.attach_published_release_assets --execute` | after publication **and** after `npm publish` (140) | no | `scripts/verify-npm-release.mjs` (144-153) | **yes** |
| `publish-mcpb.yml` : `publish` | Attach MCPB bundle and evidence to GitHub Release | `kicad-mcp-pro-<version>.mcpb`, `kicad-mcp-pro-mcpb-SHA256SUMS.txt`, `kicad-mcp-pro-mcpb-release-evidence.json` | `scripts.attach_published_release_assets --execute` | after publication | no | `targetCommitish` source check (86); `actions/attest` (164-166) | **yes** |
| `publish-protocol-schemas.yml` : `publish` | Attach evidence to GitHub Release | schemas `.tgz`, `protocol-schemas-SHA256SUMS.txt`, `protocol-schemas-sbom.cdx.json` | `scripts.attach_published_release_assets --execute` | after publication; before `npm publish` (141) | no | `isDraft == false` source check (59); `scripts/verify-npm-release.mjs` (144-153); `actions/attest` (99-100) | **yes** |
| `publish-kicad-pcm.yml` : `publish` | Attach KiCad PCM package and evidence to GitHub Release | `kicad-mcp-pro-pcm-<version>.zip`, `kicad-mcp-pro-pcm-SHA256SUMS.txt`, PCM evidence | `scripts.attach_published_release_assets --execute` | after publication | no | downloads the published zip and checks SHA256SUMS (124-150); `actions/attest` (100-102) | **yes** |

The two retired Tauri GUI mutation rows are historical only. The active
ratchet retains seven entries: one release creation and six missing-only
attachment steps. All six still count as post-publication mutations.

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

## Python production trigger boundary

A protected tag alone no longer triggers the Python publisher. The legacy
production path now starts on the published release event, verifies the
numeric Release ID, actual published state, exact tag, event and checkout
commit, and package version before building or attaching evidence. The
manual main workflow remains TestPyPI-only. The existing PyPI trusted
publisher workflow filename, environment, OIDC and provenance checks are
unchanged. This removes the tag-creation race in the legacy Python path,
but does not authorize draft-first registry publication or remove the
other autonomous published-release consumers.

## Published-release recovery without replacement

The six active attachment steps invoke the same Python module from a separate
read-only checkout of the exact workflow revision. That checkout is important
for a manual recovery from an older package tag: the reviewed upload policy
must not silently revert to the historical script. Package inputs still come
from the exact protected tag/source checkout.

The helper validates the repository, published Release ID, protected tag SHA,
local nonempty regular files, and all existing target names and asset IDs.
It compares GitHub metadata and independently downloads existing bytes by ID
before the first write. Unrelated family assets are left alone. Missing files
are uploaded by numeric Release ID without clobber; the helper rechecks live
state before each upload and independently downloads the completed target set.
A name collision or changed existing bytes stops the operation. A complete
byte-identical retry makes no upload. An interrupted upload can resume from the
same reviewed original bytes. Freshly regenerated SBOM/evidence may differ
(for example, because of timestamps or producer-run IDs); use the original
retained build artifacts for a recovery rather than overwriting history.

The default CLI is read-only; only trusted publisher/recovery workflows use
`--execute`. There is no delete, replacement, Release creation or publish
operation. Concurrent legacy writers are still possible, so these checks are
not proof of an exclusive owner lock. Registry publication, attestation
acceptance, draft-first ordering and the immutable setting remain separate
#1179 acceptance requirements.

## Ratchet: `scripts/check_release_asset_mutations.py`

The checker loads every workflow and walks each job's steps in order. It
records each step that:

- invokes the reviewed missing-only attachment module (conservatively classified as a published upload even in read-only mode);
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
- GitHub CLI and curl payload options with attached values (for example
  `-ftag_name=v1`, `--field=tag_name=v1`, `-dtag_name=v1`, and
  `--data-raw=tag_name=v1`) are classified as write requests unless an
  explicit read-only HTTP method or curl's `-G` / `--get` query mode is present.
  This is a bounded shell-argument
  recognition rule, not a complete interpreter of arbitrary scripts.
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

## Atomic cutover check (enabled in workflow policy)

`scripts/check_release_draft_cutover.py` ensures the transition cannot be
activated **partway through** a release. The current published-first mode remains
unchanged. If any Release Please package switches to `draft: true`, the policy
check requires draft and `force-tag-creation` for every release-producing package,
owner-invoked `workflow_call` publishers instead of autonomous
`push`, `release`, `schedule`, `workflow_run` or `repository_dispatch`
writers. Only `workflow_call` and PR validation events remain permitted
for migrated publishers; manual recovery dispatch belongs to the owner.
The check also requires retirement
of the existing published-release mutation allowlist, using exactly the same
effective policy supplied to the GitHub Actions checker (including overrides).
The check is enforced by the existing GitHub Actions policy
job; it adds no new services, manual release steps, or runtime calls.

These conditions are **necessary, not sufficient** to publish: source/tag
identity, exclusive writer, registry receipts, attestations, and an actual
verified draft lifecycle are still required before moving the live publisher.
No draft creation, tag push, registry write, release publication or immutable
setting change occurs through this check.

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

At the future draft-first cutover, the owner workflow must also preserve its
repository-wide `publish-release` concurrency group with
`cancel-in-progress: false` and `queue: max`. Without the stable group,
runs may overlap; with cancellation, an in-progress release may be interrupted;
with the default single pending slot, a newer run replaces a waiting release.
The static cutover check now requires all three conditions. The existing
published-first workflow remains unchanged, and no live writer lock or
end-to-end release serialization has been attested. Reusable callees must not
define a conflicting copy of the owner's group.

See GitHub's workflow concurrency reference:
https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency

When cutover is enabled, each family publisher must be invoked by the
single owner via `workflow_call`; a separate `workflow_dispatch` on any family
publisher fails the static cutover gate, even if it is described as a manual
recovery route. Recovery dispatch belongs on the owner orchestrator, not on
an independently writable family callee. `pull_request` validation may remain,
subject to existing untrusted-code permission controls. This is a necessary
structural check, **not** proof of exclusive writer ownership or authorization
to enable draft mode.

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

The preflight also binds the numeric owner and repository identities and
reads the reviewed repository `release-tags` ruleset by numeric ID. It
requires active tag update/deletion protection, exact coverage of the four
stable release families, no exclusions, and an explicitly empty bypass
list. A missing bypass list is not evidence of no bypass. GitHub exposes
that field only to callers with ruleset write access
([REST ruleset reference](https://docs.github.com/en/rest/repos/rules#get-a-repository-ruleset)).
This read-only maintainer diagnostic fails closed for restricted credentials;
do not grant a publishing worker ruleset write access to make it pass.
Replacing the ruleset or changing its coverage requires a reviewed update
to the pinned policy. This observation cannot prevent subsequent ruleset
changes and does not prove the tag's creation provenance.

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

## Read-only reusable producer metadata for opt-in families

The #1179 reusable verifier (`scripts/check_draft_producer_job.py` and
`scripts/check_draft_producer_archive.py`) now recognizes five additional
artifact roles exposed by the **default-disabled** npm, GUI, container and MCP
Registry preparers:

| Opt-in preparer | Accepted Actions artifact roles | Required verified job |
| --- | --- | --- |
| npm launcher | `npm-draft-release-evidence` | `npm / prepare` |
| Desktop GUI (historical preparer) | `gui-draft-installers`, `gui-draft-evidence` | `gui / attest-and-store` |
| Container | `container-build-source-evidence` | `container / prepare` |
| MCP Registry | `mcp-registry-draft-evidence` | `registry / prepare` |

The checks require the same exact successful, manually dispatched preflight
run on protected `main`, correct run attempt, unique GitHub job identity,
successful attestation and artifact-upload steps, and the exact Actions ZIP
SHA-256 when a downloaded archive is provided. npm and GUI require the
preceding SLSA provenance step, and GUI requires **both** final artifact
uploads in the same successful job. Adversarial tests reject skipped,
duplicated, misordered or missing steps, incorrect workflow identity, and
wrong/expired/tampered downloaded archives.

**Critical boundary:** GitHub Actions job metadata cannot cryptographically
prove *which job created an artifact* or that its contents match a signed
attestation. The container role attests **build-source evidence**, not a
published image; the Registry role attests a **prepared manifest**, not a
registry publication receipt. The helpers explicitly return
`artifactProducedByThisJobVerified: false`,
`signedAttestationVerified: false`, `registryReceiptVerified: false` where
applicable, and `publicationAuthorized: false`. No release workflow was
dispatched and no uploads, tag or immutable-release setting changed.
Cryptographic package/registry receipt verification and the exclusive
draft-first publication owner remain separate #1179 requirements.

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

## Combined owner-and-draft readiness handoff (read-only; stacked behind #1462)

The experimental script scripts/check_draft_release_owner_readiness.py composes
three independent checks, without mutating remote state: the pinned
per-family role contract, the authenticated active publish-release.yml
owner-run identity, and a live draft inventory downloaded from GitHub by
each verified numeric asset ID into an isolated temporary directory.
The shared staging reader now validates the complete remote asset name and
unique positive numeric-ID snapshot before starting any download; unknown
names, duplicate names and duplicate/invalid IDs cause an early failure.
GitHub asset state, size and any reported SHA-256 digest are checked
**after download**, together with downloaded file bytes, against the
independently pinned manifest by verify(...). It verifies the active
owner run and matching draft/tag identity a second time after the downloads,
so a detected mid-verification publication or owner change fails closed.

Run this with trusted active owner inputs and a maintainer credential that
can read the complete ruleset. It is not yet a production worker gate:

    python -m scripts.check_draft_release_owner_readiness \
      --manifest "$MANIFEST" --manifest-sha256 "$OWNER_PIN" \
      --repo "$REPO" --release-id "$NUMERIC_RELEASE_ID" \
      --tag "$TAG" --source-commit "$SOURCE_SHA" \
      --owner-run-id "$GITHUB_RUN_ID" \
      --owner-run-attempt "$GITHUB_RUN_ATTEMPT" \
      --owner-head-sha "$GITHUB_SHA"

Only gh api GET and authenticated asset download operations are used by
this command. A successful result reports exact asset role and read-back
integrity plus owner identity and observed tag protection. It explicitly reports false for
exclusiveWriterVerified, registriesVerified, attestationsVerified, and
publicationAuthorized. Repeated reads cannot prove lock ownership or prevent
races after the final read. The owner must acquire/reuse a single workflow-level
concurrency group across the complete lifecycle (including former family
writers), independently check registry/attestation provenance and authorize a
final publish transaction. This gate is deliberately not called from
production workflows yet; no real draft E2E acceptance is claimed.


## Signed Python worker input manifest (read-only, not wired)

The Python worker must verify the two exact distribution files **before**
registry publication. Do not use the final per-family draft inventory as
the pre-publication request: final registry receipts are not available yet.

The owner-side generator emits canonical unsigned JSON to stdout:

```bash
python -m scripts.check_signed_python_handoff generate \
  --directory "$DIST" --tag "$TAG" --source-commit "$SOURCE_SHA" \
  --release-id "$RELEASE_ID" --owner-run-id "$OWNER_RUN_ID" \
  --owner-attempt "$OWNER_ATTEMPT" --producer-run-id "$PRODUCER_RUN_ID" \
  --producer-attempt "$PRODUCER_ATTEMPT" --producer-artifact-id "$ARTIFACT_ID" \
  > python-worker-manifest.json
```

The future owner must attest these exact bytes under the reviewed
`publish-release.yml` workflow and separately pin the manifest SHA-256.
The read-only verifier accepts the same identity arguments with operation
`verify`, plus `--manifest python-worker-manifest.json` and
`--manifest-sha256 "$OWNER_PIN"`. Expected IDs, tag, source and pin must
come from a trusted caller, never from the downloaded request itself.
The verifier reconstructs canonical bytes from those inputs and the exact
wheel/sdist files, rejects other files and links, and verifies the signed
subject with the existing patched GitHub CLI SLSA gate (repository, owner
signer, main ref, source digest and exact invocation in both certificate
and predicate). It rechecks manifest and package bytes after verification.

This is a format and verifier contract, not a deployed signature issuer.
The current production workflows do not generate this manifest or grant
new permissions. A successful verification binds the requested draft,
tag, producer artifact and target worker workflow to a signed owner
invocation; it does not independently verify live tag protection, active
owner, artifact metadata, dispatched child, individual package provenance,
registry receipt or exclusive writer. The child run ID is assigned only
after dispatch and must be bound independently by the owner and worker.
All those checks remain mandatory before a production cutover. No new
credential or ruleset write permission is needed by this verifier.

### Live signature-only rehearsal (non-publishing)

After the reviewed workflow reaches main, the repository owner can manually
run **Signed Python handoff rehearsal (non-publishing)**. This is separate
from the existing cross-workflow transport rehearsal. The signing job creates
two deliberately invalid text fixtures named as distributions for the
synthetic version 0.0.0 and a clearly marked rehearsal envelope containing
the production-shaped request with synthetic Release/producer identifiers.
It attests only that envelope under the dedicated rehearsal signer. The
independent read-only job downloads the exact numeric artifact ID from the
same run and verifies the owner job's separately passed manifest pin,
exact package bytes, source commit, workflow signer and signed run/attempt.
It checks the manifest and package bytes again after verification.

Only the signing job has OIDC, attestation and artifact-metadata write scopes,
with no production environment, registry, Release or dispatch permission.
The verifier uses the existing patched GitHub CLI requirement (at least
2.102.0); a missing or invalid signature, CLI or digest fails closed.
Artifacts expire after three days. The production verifier retains its
separate fixed signer and rejects the rehearsal envelope. A successful
rehearsal proves real signing/verification of synthetic bytes in separate
jobs, not the production owner signer, an independently dispatched worker,
protected tag, actual Release, registry receipt or exclusive writer.
No tag or Release is created and no package is installed or published.
Do not dispatch until the workflow has passed review and merged to main.

### Maintainer-side owner and producer binding (read-only)

Before any future Python worker dispatch, the maintainer can compose the
existing owner and producer checks with the signed request:

```bash
python -m scripts.check_python_handoff_owner_binding \
  --directory "$DIST" --manifest "$MANIFEST" --manifest-sha256 "$OWNER_PIN" \
  --downloaded-zip "$PRODUCER_ZIP" --tag "$TAG" --source-commit "$SOURCE_SHA" \
  --release-id "$RELEASE_ID" --owner-run-id "$OWNER_RUN_ID" \
  --owner-attempt "$OWNER_ATTEMPT" --producer-run-id "$PRODUCER_RUN_ID" \
  --producer-attempt "$PRODUCER_ATTEMPT" --producer-artifact-id "$ARTIFACT_ID" \
  --producer-job-id "$PRODUCER_JOB_ID"
```

All expected identities and the manifest pin are independently supplied.
The diagnostic accepts only the separate completed reusable preflight
producer profile, not the legacy publisher or a synthetic rehearsal.
It checks the active production owner, draft and observed protected tag
rules; exact producer repository, run, attempt, job and artifact; safe ZIP
inventory and each package's signed provenance; and the production owner's
signed manifest. It compares the producer package digests to the
manifest's exact wheel and sdist digests, then repeats producer run/archive
identity and active owner/draft/tag checks and rechecks request bytes.
A valid signature over different owner-approved package bytes is rejected.

Run only with an already authorized maintainer credential that can read
the full tag ruleset, including bypass actors. Never grant ruleset-write
access to the registry worker. This command is not called by production
workflows yet. No production manifest issuer or live draft acceptance is
claimed. Success does not prove which job uploaded the artifact, an
independently dispatched child, registry receipts, exclusive writer lock
or publication authorization. A race after the final read remains possible.

### Post-dispatch signed worker binding (not wired)

The owner must not guess a child run ID from a workflow name or timestamp,
and the Actions bot identity alone does not identify the dispatching owner.
The GitHub REST API version 2026-03-10 returns a run ID from a successful
workflow dispatch and accepts a tag reference. After the exact successful
dispatch response, the reviewed owner will create a second canonical record
(`python-worker-dispatch.json`) binding the child run ID and attempt 1 to
the original signed request's digest and all release/owner/producer identity
fields. It must attest this record under the same production owner
workflow and invocation. An ambiguous dispatch response must fail closed;
do not blindly retry the dispatch.

The worker-side library `scripts.check_signed_python_dispatch_binding`
validates the signed record, the exact active owner and child run metadata,
numeric repository and bot identity, and the live tag commit. The expected
runtime ref, commit, run ID and attempt must originate from trusted Actions
context. The original request and exact package bytes are checked using
the manifest digest bound in the second record. Both signatures and
request bytes are verified before returning, with repeated live run/tag
checks. All expected identity inputs must be independently established;
the library does not discover them from an untrusted artifact.

Keep the complete draft and protected-tag ruleset check on the maintainer
side. GitHub documents draft listing visibility as requiring push access;
the worker must not receive contents-write or ruleset-write merely to
read draft metadata. Worker-side tag resolution is not proof of ruleset
enforcement. The library requires only run/tag reads and signature
verification, and explicitly denies dispatch causality, independent draft
and protected-tag verification, producer artifact verification, registry
receipt verification, exclusive writer and publication authorization.
The producer package verification remains a separate maintainer gate.

The production signature issuer, bounded artifact discovery and wait,
real tag-dispatch acceptance, worker receipt and publishing integration
are not implemented by this library. Existing main-ref transport and
signature-only rehearsals are not evidence of a production tag dispatch.
Never invoke an existing publishing workflow as a rehearsal. Validate the
exact tag-dispatch API shape with a reviewed non-publishing acceptance
path before relying on it. A race after the final read remains possible.

References: [workflow dispatch API](https://docs.github.com/en/rest/actions/workflows#create-a-workflow-dispatch-event),
[release visibility](https://docs.github.com/en/rest/releases/releases#list-releases),
and [GITHUB_TOKEN dispatch behavior](https://docs.github.com/en/actions/concepts/security/github_token).

#### Exact-run delivery of the signed request

The future owner stores only the two signed JSON records together in an
immutable Actions artifact named
`python-worker-request-<owner-attempt>-<worker-run-id>`.
The original package files remain in the independently verified producer
artifact. The worker uses its own Actions runtime (repository, event,
tag ref, SHA, run ID and attempt), and independently supplied owner,
producer, Release and manifest-pin inputs:

```bash
python -m scripts.check_python_worker_request_delivery discover \
  --tag "$TAG" --source-commit "$SOURCE_SHA" --release-id "$RELEASE_ID" \
  --owner-run-id "$OWNER_RUN_ID" --owner-attempt "$OWNER_ATTEMPT" \
  --producer-run-id "$PRODUCER_RUN_ID" --producer-attempt "$PRODUCER_ATTEMPT" \
  --producer-artifact-id "$PRODUCER_ARTIFACT_ID" --manifest-sha256 "$OWNER_PIN"
```

The diagnostic only accepts an untruncated run-scoped artifact listing
(up to 100 entries), one exact matching name and matching individual
artifact metadata, including repository IDs, owner run and source, size
and digest. Download the returned numeric artifact ID using the GitHub
artifact ZIP endpoint. Run the same command with `verify` instead of
`discover`, adding `--artifact-id "$REQUEST_ARTIFACT_ID"`,
`--archive "$DOWNLOADED_ZIP"` and `--directory "$DIST"`.
The verifier independently rereads metadata and requires the ZIP's exact
digest and size (maximum 64 KiB). Only the two named, nonlinked JSON
members are accepted, at most 16 KiB each. The private temporary files
are removed after checking both production-owner signatures, local
packages and exact child/owner/tag identity. The archive metadata,
archive bytes, package bytes and live identities are checked again
before returning.

Use `wait` instead of `discover` when the owner is still preparing
the request artifact. It checks live owner, child and tag identities
at each poll, and repeats those checks when the artifact appears.
Only the absence of the exact expected name in a complete listing is
retryable: at most 30 polls, five seconds between unsuccessful polls.
Expired, duplicate, truncated, changed or otherwise inconsistent
evidence and API errors stop immediately. The caller must impose an
overall job timeout that includes API latency; the poll limit alone
does not bound wall-clock time. Discovery and wait do not attest ZIP
bytes. A future orchestration job must provide trusted expected input
provenance, the exact artifact download and safe producer extraction.
This command does not publish, install, dispatch or download files
itself; its output does not establish artifact-producing job identity,
registry or exclusive-writer authority. No production workflow invokes
it yet.

#### Integrated tagged handoff rehearsal (non-publishing)

The isolated `tagged-handoff-rehearsal.yml` owner and
`tagged-handoff-worker.yml` worker exercise real tag-dispatch transport
without invoking a production publisher. After the workflow pair has
passed review and is merged, audit the exact reviewed tree's triggers and
live tag rules; create only the dedicated non-release tag
`handoff-rehearsal-<reviewed-source-sha>` at that exact main commit.
Do not create a Release or use a production tag. Run the owner workflow
on that same main commit. An intervening main change, wrong tag, rerun
or non-owner dispatch must fail closed.

The owner dispatch job alone receives Actions write access. It dispatches
once using the versioned API's returned child run ID, never a name/time
guess or blind retry. The separate signing job prepares two deterministic
synthetic records and attests them with the rehearsal-only workflow
identity. The worker receives read-only contents, Actions and attestation
access. Dispatch supplies the numeric owner run ID as an untrusted
selector, not authorization. The worker validates its ASCII decimal
format, rejects its own run ID, and directly reads the exact owner
and worker runs and live tag. It requires the active owner workflow,
trusted actor IDs, exact source and attempts; it never searches a
filtered owner run listing. Dispatch preflight requires an immediately
in-progress owner. During delivery and receipt checks, a verified
nonterminal owner may briefly be queued between jobs. Only those
known pending states allow up to 12 polls, five seconds apart, per
identity check. Every poll checks exact owner, worker and tag identity;
acceptance still requires an in-progress owner. Terminal outcomes,
identity mismatches and API failures stop immediately. Job timeouts
bound the combined polling and API latency. The subsequently verified
signed binding must match the worker's own run ID. It waits at most 30 polls with
five seconds between absent-artifact polls. Only the exact unique
owner ZIP (maximum 64 KiB) is accepted; it must contain the two bounded
records, each at most 16 KiB. The download pipeline caps bytes and the
verifier compares exact metadata, digest and regenerated record bytes,
verifies both owner attestations, and repeats live identity checks.

The completed child returns a receipt binding the source, tag, owner
and worker IDs, request artifact ID, archive hash and both record hashes.
The owner waits at most 60 polls, checks the exact successful child and
its unique tag-scoped receipt ZIP, and compares the entire receipt against
the independently regenerated expected value. All jobs have explicit
timeouts. Rehearsal signatures and receipt checks do not authorize any
publication or establish production draft, producer, protected-tag,
registry or exclusive-writer acceptance. The tag metadata shape still
requires an actual non-publishing run. No registry environment or
production signing identity is used.
