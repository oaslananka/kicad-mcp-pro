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
