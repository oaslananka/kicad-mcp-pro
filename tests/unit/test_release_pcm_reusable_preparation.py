"""PCM preparation must be artifact-only until a draft owner accepts it (#1179)."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/prepare-kicad-pcm.yml"
LEGACY = ROOT / ".github/workflows/publish-kicad-pcm.yml"


def _config() -> dict:
    data = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def _steps() -> list[dict]:
    return _config()["jobs"]["prepare"]["steps"]


def test_pcm_source_bound_reusable_inputs_with_legacy_triggers_retained() -> None:
    data = _config()
    events = data[True]
    assert set(events["workflow_call"]["inputs"]) == {"tag", "source_commit"}
    for item in events["workflow_call"]["inputs"].values():
        assert item["required"] is True
        assert item["type"] == "string"
    assert set(events) == {"workflow_call"}
    legacy_events = yaml.safe_load(LEGACY.read_text(encoding="utf-8"))[True]
    assert legacy_events["release"]["types"] == ["published"]
    assert "workflow_dispatch" in legacy_events
    assert "workflow_call" not in legacy_events
    gate = data["jobs"]["prepare"]["if"]
    permissions = data["jobs"]["prepare"]["permissions"]
    assert permissions["contents"] == "read"
    assert "environment" not in data["jobs"]["prepare"]
    assert "github.ref == 'refs/heads/main'" in gate
    assert "github.repository == 'oaslananka/kicad-mcp-pro'" in gate
    assert "inputs.source_commit != ''" in gate
    assert "inputs.source_commit == ''" not in gate


def test_pcm_preparation_attests_but_never_reads_or_mutates_release() -> None:
    steps = _steps()
    source = next(x for x in steps if x.get("name") == "Verify release source and package version")
    assert 'if [[ -z "$PREPARE_SOURCE" ]]' not in source["run"]
    assert '[[ "$PREPARE_SOURCE" =~ ^[0-9a-f]{40}$ ]] || exit 1' in source["run"]
    assert source["env"]["PREPARE_SOURCE"] == "$" + "{{ inputs.source_commit }}"
    assert 'test "$source_commit" = "$tag_commit"' in source["run"]
    assert 'test "$package_version" = "$VERSION"' in source["run"]
    check = next(x for x in steps if x.get("name") == "Verify reusable preparation source identity")
    assert "if" not in check
    assert '[[ "$CALLER_SHA" == "$EXPECTED_SOURCE" ]] || exit 1' in check["run"]
    assert '[[ "$(git rev-parse HEAD)" == "$EXPECTED_SOURCE" ]] || exit 1' in check["run"]
    checkout = next(x for x in steps if "actions/checkout@" in x.get("uses", ""))
    assert checkout["with"]["ref"] == "refs/tags/" + "$" + "{{ steps.release.outputs.tag }}"
    assert "refs/tags/" + "$" + "{release_tag}^{commit}" in source["run"]
    identity_index = next(
        i
        for i, item in enumerate(steps)
        if item.get("name") == "Verify reusable preparation source identity"
    )
    checkout_index = next(
        i for i, item in enumerate(steps) if "actions/checkout@" in item.get("uses", "")
    )
    setup_index = next(
        i for i, item in enumerate(steps) if "astral-sh/setup-uv@" in item.get("uses", "")
    )
    assert identity_index == checkout_index + 1
    assert identity_index < setup_index
    assert any(x.get("name") == "Attest KiCad PCM package" for x in steps)
    assert any(x.get("name") == "Store KiCad PCM release evidence" for x in steps)
    assert "gh release" not in WORKFLOW.read_text(encoding="utf-8")
    assert "npm publish" not in WORKFLOW.read_text(encoding="utf-8")
    assert all("gh release" not in step.get("run", "") for step in steps)
    assert "gh release upload" in LEGACY.read_text(encoding="utf-8")


def _simulate_source_step(
    tmp_path: Path, *, prepare: bool, matching: bool = True, tag_exists: bool = True
) -> tuple[int, bool]:
    source = next(
        x for x in _steps() if x.get("name") == "Verify release source and package version"
    )
    sha = "a" * 40
    tag_sha = sha if matching else "b" * 40
    scripts = tmp_path / "bin"
    scripts.mkdir()
    (scripts / "git").write_text(
        '#!/bin/sh\ncase "$*" in\n'
        '  "rev-parse HEAD") echo ' + sha + ";;\n"
        '  "rev-list -n 1 refs/tags/mcp-server-v4.5.0^{commit}") '
        '[ "$TAG_PRESENT" = yes ] || exit 91; echo ' + tag_sha + ";;\n"
        "  *) exit 91;;\n"
        "esac\n",
        encoding="utf-8",
    )
    (scripts / "python3").write_text("#!/bin/sh\necho 4.5.0\n", encoding="utf-8")
    marker = tmp_path / "gh-invoked"
    (scripts / "gh").write_text(
        '#!/bin/sh\necho yes > "$GH_INVOKED"\necho ' + sha + "\n",
        encoding="utf-8",
    )
    for path in scripts.iterdir():
        path.chmod(0o755)
    env = {
        **os.environ,
        "PATH": str(scripts) + os.pathsep + os.environ["PATH"],
        "RELEASE_TAG": "mcp-server-v4.5.0",
        "VERSION": "4.5.0",
        "GITHUB_REPOSITORY": "oaslananka/kicad-mcp-pro",
        "GH_INVOKED": str(marker),
        "PREPARE_SOURCE": sha if prepare else "",
        "TAG_PRESENT": "yes" if tag_exists else "no",
    }
    result = subprocess.run(
        ["/bin/bash", "-euo", "pipefail", "-c", source["run"]],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    return result.returncode, marker.exists()


@pytest.mark.skipif(os.name == "nt", reason="POSIX Bash fixture; release workflow runs on Ubuntu")
def test_pcm_prepare_succeeds_without_release_lookup(tmp_path: Path) -> None:
    code, gh = _simulate_source_step(tmp_path, prepare=True)
    assert code == 0
    assert gh is False


@pytest.mark.skipif(os.name == "nt", reason="POSIX Bash fixture; release workflow runs on Ubuntu")
def test_pcm_empty_source_is_rejected_without_release_lookup(tmp_path: Path) -> None:
    code, gh = _simulate_source_step(tmp_path, prepare=False)
    assert code != 0
    assert gh is False


@pytest.mark.skipif(os.name == "nt", reason="POSIX Bash fixture; release workflow runs on Ubuntu")
def test_pcm_prepare_rejects_wrong_protected_tag(tmp_path: Path) -> None:
    code, gh = _simulate_source_step(tmp_path, prepare=True, matching=False)
    assert code != 0
    assert gh is False


@pytest.mark.skipif(os.name == "nt", reason="POSIX Bash fixture; release workflow runs on Ubuntu")
def test_pcm_same_name_branch_cannot_replace_missing_tag(tmp_path: Path) -> None:
    # Git has a ref named refs/heads/mcp-server-v4.5.0 but no tag of that name.
    # The exact refs/tags/...^{commit} lookup must fail closed, not use the branch.
    code, gh = _simulate_source_step(tmp_path, prepare=True, tag_exists=False)
    assert code != 0
    assert gh is False
