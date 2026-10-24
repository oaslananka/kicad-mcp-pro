"""Compose read-only #1179 owner, family, and downloaded draft-asset checks.

Even a successful result does NOT authorize upload/publish: there is no
exclusive-writer proof, registry digest verification or attestation acceptance.
No call in this module can mutate a GitHub Release.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Protocol

from scripts.check_draft_release_inventory import verify
from scripts.check_draft_release_owner import OwnerClient, OwnerGitHubCLI, verify_owner
from scripts.check_release_family_inventory import verify_family
from scripts.stage_draft_release_assets import DraftClient, _downloaded_snapshot


class DownloadableOwnerClient(OwnerClient, DraftClient, Protocol):
    """Read-only code consumes only the download side of this API client."""


def check_readiness(
    client: DownloadableOwnerClient,
    *,
    manifest_path: Path,
    manifest_sha256: str,
    repo: str,
    release_id: int,
    tag: str,
    source_commit: str,
    owner_run_id: int,
    owner_run_attempt: int,
    owner_head_sha: str,
) -> dict[str, Any]:
    """Fail closed if any independently scoped read-only evidence differs.

    Check family roles before any API read, then owner identity, live Release
    byte inventory and owner identity again. A race after the final read
    remains possible, so the output MUST NOT be used as publication authority.
    """
    family = verify_family(manifest_path, manifest_sha256, tag, source_commit)

    def check_owner() -> dict[str, object]:
        return verify_owner(
            client,
            repo=repo,
            release_id=release_id,
            tag=tag,
            source_commit=source_commit,
            owner_run_id=owner_run_id,
            owner_run_attempt=owner_run_attempt,
            owner_head_sha=owner_head_sha,
        )

    initial = check_owner()
    release = client.release(repo, release_id)
    protected_tag_sha = client.tag_commit(repo, tag)
    with TemporaryDirectory(prefix="kicad-owner-readiness-1179-") as temporary:
        downloaded_assets = Path(temporary)
        _downloaded_snapshot(client, repo, release, downloaded_assets, set(family["assetNames"]))
        verify(
            directory=downloaded_assets,
            manifest_path=manifest_path,
            manifest_sha256=manifest_sha256,
            release=release,
            repository=repo,
            tag=tag,
            source_commit=source_commit,
            tag_commit=protected_tag_sha,
        )
    final = check_owner()
    if final != initial:
        raise ValueError("owner identity changed during readiness check")
    return {
        "repository": repo,
        "releaseId": release_id,
        "releaseTag": tag,
        "sourceCommit": source_commit,
        "ownerRunId": owner_run_id,
        "ownerRunAttempt": owner_run_attempt,
        "family": family["family"],
        "assetCount": len(family["assetNames"]),
        "familyAssetNamesVerified": True,
        "ownerIdentityVerified": True,
        "draftAssetsVerified": True,
        "downloadedByAssetId": True,
        "registriesVerified": False,
        "attestationsVerified": False,
        "exclusiveWriterVerified": False,
        "publicationAuthorized": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--release-id", type=int, required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--owner-run-id", type=int, required=True)
    parser.add_argument("--owner-run-attempt", type=int, required=True)
    parser.add_argument("--owner-head-sha", required=True)
    args = parser.parse_args()
    try:
        result = check_readiness(
            OwnerGitHubCLI(),
            manifest_path=args.manifest,
            manifest_sha256=args.manifest_sha256,
            repo=args.repo,
            release_id=args.release_id,
            tag=args.tag,
            source_commit=args.source_commit,
            owner_run_id=args.owner_run_id,
            owner_run_attempt=args.owner_run_attempt,
            owner_head_sha=args.owner_head_sha,
        )
    except (ValueError, OSError) as exc:
        parser.exit(2, f"draft owner readiness: FAIL: {exc}\n")
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
