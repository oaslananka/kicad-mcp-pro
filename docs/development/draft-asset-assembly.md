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
