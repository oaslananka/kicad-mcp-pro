"""PCM preparation must be artifact-only until a draft owner accepts it (#1179)."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/publish-kicad-pcm.yml"


def _config() -> dict:
    data = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def _steps() -> list[dict]:
    return _config()["jobs"]["publish"]["steps"]


def test_pcm_source_bound_reusable_inputs_with_legacy_triggers_retained() -> None:
    data = _config()
    events = data[True]
    assert set(events["workflow_call"]["inputs"]) == {"tag", "source_commit"}
    for item in events["workflow_call"]["inputs"].values():
        assert item["required"] is True
        assert item["type"] == "string"
    assert events["release"]["types"] == ["published"]
    assert "workflow_dispatch" in events
    gate = data["jobs"]["publish"]["if"]
    assert "github.ref == 'refs/heads/main'" in gate
    assert "inputs.source_commit != ''" in gate
    assert "inputs.source_commit == ''" in gate


def test_pcm_preparation_attests_but_never_reads_or_mutates_release() -> None:
    steps = _steps()
    source = next(x for x in steps if x.get("name") == "Verify release source and package version")
    assert 'if [[ -z "$PREPARE_SOURCE" ]]' in source["run"]
    assert source["env"]["PREPARE_SOURCE"] == "$" + "{{ inputs.source_commit }}"
    assert 'test "$source_commit" = "$tag_commit"' in source["run"]
    assert 'test "$package_version" = "$VERSION"' in source["run"]
    check = next(x for x in steps if x.get("name") == "Verify reusable preparation source identity")
    assert check["if"] == "inputs.source_commit != ''"
    assert '[[ "$CALLER_SHA" == "$EXPECTED_SOURCE" ]]' in check["run"]
    assert '[[ "$(git rev-parse HEAD)" == "$EXPECTED_SOURCE" ]]' in check["run"]
    assert any(x.get("name") == "Attest KiCad PCM package" for x in steps)
    assert any(x.get("name") == "Store KiCad PCM release evidence" for x in steps)
    for name in (
        "Attach KiCad PCM package and evidence to GitHub Release",
        "Verify published PCM digest",
    ):
        step = next(x for x in steps if x.get("name") == name)
        assert step["if"] == "inputs.source_commit == ''"
    assert "gh release create" not in WORKFLOW.read_text(encoding="utf-8")
    assert "gh release edit" not in WORKFLOW.read_text(encoding="utf-8")


def _simulate_source_step(
    tmp_path: Path, *, prepare: bool, matching: bool = True
) -> tuple[int, bool]:
    source = next(
        x for x in _steps() if x.get("name") == "Verify release source and package version"
    )
    sha = "a" * 40
    tag_sha = sha if matching else "b" * 40
    scripts = tmp_path / "bin"
    scripts.mkdir()
    (scripts / "git").write_text(
        '#!/bin/sh\ncase "$1 $2" in\n'
        '  "rev-parse HEAD") echo ' + sha + ";;\n"
        '  "rev-list -n") echo ' + tag_sha + ";;\n"
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
    }
    result = subprocess.run(
        ["/bin/bash", "-euo", "pipefail", "-c", source["run"]],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    return result.returncode, marker.exists()


def test_pcm_prepare_succeeds_without_release_lookup(tmp_path: Path) -> None:
    code, gh = _simulate_source_step(tmp_path, prepare=True)
    assert code == 0
    assert gh is False


def test_pcm_legacy_release_target_check_unchanged(tmp_path: Path) -> None:
    code, gh = _simulate_source_step(tmp_path, prepare=False)
    assert code == 0
    assert gh is True


def test_pcm_prepare_rejects_wrong_protected_tag(tmp_path: Path) -> None:
    code, gh = _simulate_source_step(tmp_path, prepare=True, matching=False)
    assert code != 0
    assert gh is False
