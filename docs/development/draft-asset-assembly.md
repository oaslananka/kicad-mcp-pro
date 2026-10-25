# Offline mcp-server draft asset assembly (#1179)

This is a **preparation-only** building block for a future single-owner release
workflow. It combines four separately downloaded GitHub Actions artifacts into
one SHA-256-pinned release inventory:

| Producer artifact | Supplied as | Release assets |
| --- | --- | --- |
| `python-dist` | `--python-dist` | Wheel and sdist |
| `python-release-evidence` | `--python-evidence` | Renamed Python SHA256SUMS, SBOM, and evidence |
| `mcpb-release-evidence` | `--mcpb` | MCPB, checksum, and evidence |
| `kicad-pcm-release-evidence` | `--pcm` | PCM ZIP, checksum, and evidence |

After the future orchestration has **independently** verified the exact repository,
job workflow, successful producer run/attempt, release tag, tag commit, source
commit and uploaded artifact identity, it may download each named artifact to
a **separate directory** and run:

```bash
python -m scripts.assemble_mcp_server_draft_assets \
  --tag mcp-server-v4.5.0 \
  --source-commit "$REVIEWED_MAIN_SHA" \
  --python-dist "$DOWNLOADS/python-dist" \
  --python-evidence "$DOWNLOADS/python-release-evidence" \
  --mcpb "$DOWNLOADS/mcpb-release-evidence" \
  --pcm "$DOWNLOADS/kicad-pcm-release-evidence" \
  --output "$STAGING/mcp-server-approved"
```

The output contains `assets/` (exactly 11 approved assets) and `manifest.json`.
The JSON result includes the **external manifest SHA-256 pin**, which must be
passed independently to the existing `check_release_family_inventory`,
`plan_draft_release_retry`, and `check_draft_release_owner_readiness`
gates. Input names are exact and every source folder must contain only expected
regular nonempty files. Sidecar checksums, available source metadata and
family/version rules are checked before and after the copy. An existing output
folder is never overwritten; failed validation never publishes or uploads.

**Security / publication boundary:** Downloaded file paths alone are **not**
proof of their workflow origin, checked-out commit or GitHub attestations.
The PCM evidence currently pins version and local artifact digest, but *does
not carry a source commit*. No provenance, signature, registry digest, exclusive
writer, draft upload/readback or final publication authority is implied by
this offline operation. The script never fetches GitHub, creates Releases,
writes to a registry, modifies secrets or grants authorization to publish.

Only the mcp-server family is supported; GUI, npm and protocol-schemas need
their own separately reviewed assembly/registry checks. Existing published-first
behavior remains unchanged until the entire orchestrator is independently
accepted and the atomic cutover policy permits the transition.

## Read-only Actions ZIP identity check

Before extracting each downloaded Actions ZIP, a future automation can query
GitHub REST (via authenticated `gh api`) and verify its exact completed,
successful `main` workflow run, `run_attempt`, same-repository ID,
allowed publisher workflow, nonexpired archive ID/name, and the **GitHub
artifact archive SHA-256** against the separately downloaded ZIP bytes:

```bash
python -m scripts.check_draft_producer_archive \
  --repo oaslananka/kicad-mcp-pro \
  --role mcpb-release-evidence \
  --run-id "$APPROVED_PRODUCER_RUN_ID" \
  --run-attempt "$APPROVED_PRODUCER_RUN_ATTEMPT" \
  --artifact-id "$APPROVED_MCPB_ARTIFACT_ID" \
  --head-sha "$REVIEWED_MAIN_SHA" \
  --downloaded-zip "$DOWNLOADS/mcpb-release-evidence.zip"
```

Perform this check for **all four exact artifact names**, using an independently
approved source SHA and producer IDs. A non-main or pull-request run, failed or
still-running producer, changed repo ID, unrecognized workflow, missing digest,
stale archive or substituted ZIP **fails closed**. Extracting the ZIP still
requires safe zip-member path validation; the check itself never extracts.

This gate is deliberately limited: a workflow run may contain many jobs, and
archive metadata alone does **not** prove the exact producing job or
cryptographic attestation. It accepts **completed separate producer
workflow-dispatch runs only**; a future in-progress reusable-workflow owner
must use separately reviewed per-job evidence instead of weakening this gate.
The check never authorizes a publish or performs GitHub writes. It also
does not independently authorize the input `--run-id`/`--artifact-id` values:
the single owner must freeze them from a separately trusted plan.

## Exact producer-job readiness (separate from artifact ZIP)

Before approving a completed producer workflow's output, confirm the exact
job ID and run attempt with a separate read-only GitHub Actions job API check:

```bash
python -m scripts.check_draft_producer_job \
  --repo oaslananka/kicad-mcp-pro \
  --role mcpb-release-evidence \
  --run-id "$APPROVED_PRODUCER_RUN_ID" \
  --run-attempt "$APPROVED_PRODUCER_RUN_ATTEMPT" \
  --job-id "$APPROVED_PRODUCER_JOB_ID" \
  --source-commit "$REVIEWED_MAIN_SHA"
```

This rechecks the protected repository, workflow path, successful main
workflow-dispatch run/attempt, exact expected build job, successful attestation
step, and artifact upload step in the correct sequence. The job collection must
be complete rather than silently trusting a truncated first page. The archive
validator now refuses release-owner workflow paths in place of the **actual
per-family producer path**, even if an otherwise plausible archive was uploaded.

A successful Actions job is only **job metadata evidence**. GitHub artifact
metadata does not directly cryptographically link the archive to a particular
job within the run. The output therefore explicitly returns
`artifactProducedByThisJobVerified=false`, and never authorizes publication.

## Safely extract a previously verified ZIP

After `check_draft_producer_archive`, use the extraction gate instead of
unfiltered `unzip` or `zipfile.extractall`:

```bash
python -m scripts.extract_draft_producer_zip \
  --role mcpb-release-evidence \
  --tag mcp-server-v4.5.0 \
  --run-id "$APPROVED_PRODUCER_RUN_ID" \
  --run-attempt "$APPROVED_PRODUCER_RUN_ATTEMPT" \
  --artifact-id "$APPROVED_MCPB_ARTIFACT_ID" \
  --head-sha "$REVIEWED_MAIN_SHA" \
  --downloaded-zip "$DOWNLOADS/mcpb-release-evidence.zip" \
  --output "$EXTRACTED/mcpb"
```

Extraction **rechecks** GitHub ZIP digest and metadata, requires the exact
flat filename set for that package version, rejects unsafe paths, symlinks,
encrypted/empty members, duplicates and excessive decompression sizes/ratios.
After CRC-checked extraction it rehashes the original ZIP and atomically
creates a *new* output directory. No file gets executed, published or
uploaded by the extractor.

## Signed package acceptance

On each extracted distributable (both Python wheel/sdist, MCPB and PCM ZIP),
invoke the cryptographic GitHub attestation verifier:

```bash
python -m scripts.check_signed_draft_asset \
  --kind mcpb \
  --package "$EXTRACTED/mcpb/kicad-mcp-pro-4.5.0.mcpb" \
  --tag mcp-server-v4.5.0 \
  --source-commit "$REVIEWED_MAIN_SHA"
```

The gate requires a **successful** `gh attestation verify` with the exact
`--repo`, individual allowed `--signer-workflow`, `--source-ref
refs/heads/main`, `--source-digest`, SLSA provenance predicate and JSON
statement subject digest/name matching the actual package bytes. Empty or
mismatched cryptographic verification results fail. This is not a local
signature verifier: **GitHub CLI performs cryptographic verification**, and
its online verification must be tested on a real signed producer package
before enabling any publication.

**Important incompatibility to resolve during live acceptance:** a
producer emitting *only* a CycloneDX SBOM attestation rather than SLSA
provenance cannot pass the stricter SLSA gate, even when its existing
`actions/attest` step succeeds. Never silently equate SBOM generation with
cryptographic source provenance; update/review the producer's attestation
contract first if necessary. No live signed package acceptance is yet claimed.

### Cryptographic SLSA producer-run identity (real v4.4.0 acceptance)

GitHub's **verified** `https://slsa.dev/provenance/v1` JSON includes two
independent statements of the producing workflow invocation: the predicate
`runDetails.metadata.invocationId` and the Sigstore certificate's
`runInvocationURI`. The read-only `check_signed_draft_asset` command
can now require that **both** identify the exact independently approved
`producer_run_id` and `producer_run_attempt`:

```bash
python -m scripts.check_signed_draft_asset   --kind mcpb   --package "$EXTRACTED/mcpb/kicad-mcp-pro-4.5.0.mcpb"   --tag mcp-server-v4.5.0   --source-commit "$REVIEWED_MAIN_SHA"   --source-ref refs/heads/main   --producer-run-id "$APPROVED_PRODUCER_RUN_ID"   --producer-run-attempt "$APPROVED_PRODUCER_RUN_ATTEMPT"
```

These two flags must be provided together. The expected run and attempt IDs
must come from the separately validated owner plan, **not** be inferred from
untrusted package contents. Even if multiple valid attestations exist for
the same artifact, the check rejects the package unless at least one
cryptographically verified subject matches the actual package digest and
**both** invocation URIs match the expected run/attempt. Supplying no run
ID keeps the standalone historical signature check but explicitly returns
`producerRunInvocationVerified=false`. The owner must require `true`.

**Real live test:** the already-published v4.4.0 MCPB (SHA-256
`7e429e76cac30f95cce7b11ce86dced32ef0f2f57bbe3446b0795c8f505da3f3`)
was downloaded read-only from GitHub and verified online with exact tag,
signer, source SHA `285be423edd2d16c799f4cb20b60858a4a729010`
and producing run `40050705072` attempt `1`. **PASS**. The
same signed artifact with run attempt `2` was **rejected**. The actual
signed predicate and certificate independently contained
`https://github.com/oaslananka/kicad-mcp-pro/actions/runs/40050705072/attempts/1`.

This adds **cryptographic linkage to the workflow run/attempt**, not proof
of the particular producer **job**, identity/approval of an owner plan,
registry receipt, exclusive writer or readiness to make a Release public.
Those remain separate required gates. No new attestation, tag or Release
was created by this test.

These checks still do **not** prove registry receipts, GitHub artifact-to-job
binding, the exclusive writer lock, actual draft Release upload/read-back or
authority to switch releases public. A single automatic owner must connect
them and validate every independent result before the atomic draft-first
cutover is reviewed. The current published-first flow remains untouched.

## Real published v4.4.0 attestation acceptance — 2026-10-25

Read-only GitHub Release downloads and online `gh attestation verify` were
exercised against the existing `mcp-server-v4.4.0` tag
(`285be423edd2d16c799f4cb20b60858a4a729010`). The checks did **not**
write any tag, release, registry record or new attestation:

- **MCPB** `kicad-mcp-pro-4.4.0.mcpb`: SHA-256
  `7e429e76cac30f95cce7b11ce86dced32ef0f2f57bbe3446b0795c8f505da3f3`,
  exact signer `publish-mcpb.yml`, exact tag source ref and source commit:
  GitHub cryptographic **SLSA provenance SUCCESS**.
- **KiCad PCM** `kicad-mcp-pro-pcm-4.4.0.zip`: SHA-256
  `d22f630c40d019d997ecea8a17b7b8b66a90461c816641d2182ba5d5d4699a3d`,
  exact signer `publish-kicad-pcm.yml`, tag ref and source commit:
  GitHub cryptographic **SLSA provenance SUCCESS**.
- **Python wheel and sdist**: `gh attestation verify` with the required
  SLSA provenance predicate returned HTTP 404 — **SLSA FAIL / absent**, not
  accepted. The same wheel's `https://cyclonedx.org/bom` **SBOM attestation
  did verify** for both wheel and sdist subjects, with the expected signer,
  tag ref and source commit. A signed SBOM is **not a substitute** for
  signed SLSA provenance.

The tagged-release source-ref acceptance mode requires explicit
`--source-ref refs/tags/mcp-server-v4.4.0` and matches it to
`--tag mcp-server-v4.4.0`. The default for future owner-invoked
prepare-on-main builds is still `refs/heads/main`. An unrelated tag or
branch cannot be supplied. All results keep `publicationAuthorized=false`.

To close the Python gap **before** any new draft publication, add a
separately signed, checksum-bound SLSA provenance attestation in the existing
Python build job **in addition to**, not instead of, the CycloneDX SBOM
attestation. Recheck a real successfully completed producer workflow under
the reviewed main ref before declaring any owner release readiness.

The Python producer job acceptance now additionally requires **both**
`Attest Python SLSA build provenance` and the existing
`Attest Python distributions` (CycloneDX SBOM) step to succeed, in that
order, before either Actions artifact upload. The additive SLSA workflow
change is staged independently on
`feature/1179-python-slsa-provenance-20261025`; the job acceptance cannot
succeed for a legacy Python producer that has only an SBOM attestation.

## Read-only whole-bundle signature/run consistency (staged, #1179)

Instead of passing unrelated evidence JSONs to a future owner and trusting
that their source IDs match, the **nonpublishing** command
`scripts.check_signed_draft_producer_bundle` composes the exact four existing
security gates for a **separately completed, successful main
`workflow_dispatch` producer** into a single fail-closed operation:

```bash
python -m scripts.check_signed_draft_producer_bundle \
  --repo oaslananka/kicad-mcp-pro \
  --role mcpb-release-evidence \
  --tag mcp-server-v4.5.0 \
  --source-commit "$REVIEWED_MAIN_SHA" \
  --run-id "$APPROVED_PRODUCER_RUN_ID" \
  --run-attempt "$APPROVED_PRODUCER_RUN_ATTEMPT" \
  --job-id "$APPROVED_PRODUCER_JOB_ID" \
  --artifact-id "$APPROVED_MCPB_ARTIFACT_ID" \
  --downloaded-zip "$DOWNLOADS/mcpb-release-evidence.zip"
```

It independently checks the **specific completed Actions producer job**,
the approved ZIP artifact ID and GitHub-recorded archive SHA256, safe exact
ZIP contents in an isolated temporary directory, then *every* signable
package with GitHub CLI's cryptographic **SLSA** verification. The package
signature's attested `invocationId` **and** signed certificate
`runInvocationURI` must match the same separately approved producing
run and attempt used by the job and ZIP gates. Signable roles are
`python-dist` (both wheel and sdist), `mcpb-release-evidence` and
`kicad-pcm-release-evidence`. The `python-release-evidence` artifact is
**not** falsely treated as a signed package: validate its ZIP/job metadata
with the separate existing tools before the 11-asset assembly.

The command **never preserves the extracted files, uploads them, grants
publication authorization, or changes a Release**. It reports the exact
same run/job/artifact IDs, archive digest and per-package SLSA digest, but
retains `artifactProducedByThisJobVerified=false`,
`registryReceiptVerified=false`, `exclusiveWriterVerified=false` and
`publicationAuthorized=false`.

The approved run/job/artifact identifiers must be supplied from a separately
reviewed, frozen owner plan, **never chosen from the package, ZIP or an
untrusted pull request**. Although the signature now cryptographically
binds the package to the run and attempt, it does **not** include a signed
job ID; the GitHub archive API likewise does not cryptographically bind
the ZIP to an individual job. Independent checks of that job's successful
attestation/upload steps are metadata evidence, not an equivalent signature.

**Current limitation:** the old ZIP/job verifiers demand a **fully completed
main `workflow_dispatch` run**, and they deliberately reject release/tag
events and active reusable-workflow runs. This new composition does not
secretly broaden that contract. A genuine owner-orchestrated `workflow_call`
must get a **separately reviewed job-scoped acceptance model** before its
own run has completed. Historical live SLSA validation (v4.4.0 MCPB and
PCM) demonstrates the underlying signed invocation fields, not this
completed-main-workflow composition. No end-to-end owner publication
acceptance is yet claimed.
