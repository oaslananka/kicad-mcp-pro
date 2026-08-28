from __future__ import annotations

import json
from pathlib import Path

from scripts.check_github_actions_policy import has_sha_pinned_action

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "publish-kicad-pcm.yml"


def test_pcm_release_workflow_exists_and_is_release_tag_scoped() -> None:
    assert WORKFLOW.is_file()
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "release:" in workflow
    assert "types: [published]" in workflow
    assert "workflow_dispatch:" in workflow
    assert "mcp-server-v" in workflow
    assert "startsWith(github.event.release.tag_name, 'mcp-server-v')" in workflow
    assert "startsWith(inputs.tag, 'mcp-server-v')" in workflow


def test_pcm_release_workflow_verifies_source_builds_attests_and_rechecks_publish() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert has_sha_pinned_action(workflow, "actions/checkout")
    assert has_sha_pinned_action(workflow, "actions/attest")
    assert has_sha_pinned_action(workflow, "actions/upload-artifact")
    assert 'source_commit="$(git rev-parse HEAD)"' in workflow
    assert 'tag_commit="$(git rev-list -n 1 "$release_tag")"' in workflow
    assert 'test "$source_commit" = "$tag_commit"' in workflow
    assert 'test "$release_target" = "$source_commit"' in workflow
    assert "scripts/build_kicad_pcm.py" in workflow
    assert "--verify" in workflow
    assert "kicad-mcp-pro-pcm-SHA256SUMS.txt" in workflow
    assert (
        "subject-checksums: release-assets/kicad-pcm/kicad-mcp-pro-pcm-SHA256SUMS.txt" in workflow
    )
    assert 'gh release upload "$release_tag" release-assets/kicad-pcm/* --clobber' in workflow
    assert "Verify published PCM digest" in workflow
    assert 'gh release download "$release_tag"' in workflow
    assert "sha256sum --check kicad-mcp-pro-pcm-SHA256SUMS.txt" in workflow


def test_pcm_release_workflow_permissions_match_hardened_policy() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    policy = json.loads((ROOT / ".github" / "actions-policy.json").read_text(encoding="utf-8"))

    assert "permissions:\n  contents: read" in workflow
    assert "artifact-metadata: write" in workflow
    assert "attestations: write" in workflow
    assert "contents: write" in workflow
    assert "id-token: write" in workflow
    assert policy["workflow_write_permissions"]["publish-kicad-pcm.yml"]["publish"] == [
        "artifact-metadata",
        "attestations",
        "contents",
        "id-token",
    ]


def test_pr_ci_validates_pcm_without_publishing() -> None:
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    release_validation = (ROOT / ".github" / "workflows" / "release.yml").read_text(
        encoding="utf-8"
    )

    assert "Validate deterministic KiCad PCM package" in ci
    assert "scripts/build_kicad_pcm.py" in ci
    assert "--verify" in ci
    release_metadata_block = ci.split("  release-metadata:", 1)[1].split("\n  mcp-server:", 1)[0]
    assert "gh release upload" not in release_metadata_block
    assert '"packaging/kicad-pcm/**"' in release_validation
    assert '"packages/kicad-plugin/**"' in release_validation
    assert '"scripts/build_kicad_pcm.py"' in release_validation
