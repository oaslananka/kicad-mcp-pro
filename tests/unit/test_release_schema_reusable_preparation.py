"""Protocol schema preparation must not publish or touch an uncreated Release (#1179)."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/publish-protocol-schemas.yml"


def _config() -> dict:
    data = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def _steps() -> list[dict]:
    return _config()["jobs"]["publish"]["steps"]


def test_schema_prep_has_exact_inputs_and_preserves_legacy_events() -> None:
    config = _config()
    events = config[True]
    inputs = events["workflow_call"]["inputs"]
    assert set(inputs) == {"tag", "source_commit"}
    assert all(i["type"] == "string" and i["required"] is True for i in inputs.values())
    assert events["release"]["types"] == ["published"]
    assert "workflow_dispatch" in events
    condition = config["jobs"]["publish"]["if"]
    assert "github.ref == 'refs/heads/main'" in condition
    assert "github.repository == 'oaslananka/kicad-mcp-pro'" in condition
    assert "inputs.source_commit != ''" in condition
    assert "inputs.source_commit == ''" in condition


def test_schema_source_verified_before_installs_and_preparation_is_artifact_only() -> None:
    steps = _steps()
    checkout = next(i for i, s in enumerate(steps) if "actions/checkout@" in s.get("uses", ""))
    verify = next(
        i for i, s in enumerate(steps) if s.get("name") == "Verify immutable release source"
    )
    setup = next(i for i, s in enumerate(steps) if "astral-sh/setup-uv@" in s.get("uses", ""))
    assert verify == checkout + 1
    assert verify < setup
    assert "inputs.tag ||" in steps[checkout]["with"]["ref"]
    script = steps[verify]["run"]
    assert steps[verify]["env"]["PREPARE_SOURCE"] == "$" + "{{ inputs.source_commit }}"
    assert steps[verify]["env"]["CALLER_SHA"] == "$" + "{{ github.sha }}"
    assert '[[ "$CALLER_SHA" == "$PREPARE_SOURCE" ]]' in script
    assert '[[ "$(git rev-parse HEAD)" == "$PREPARE_SOURCE" ]]' in script
    assert 'test "$tag_sha" = "$head_sha"' in script
    assert 'if [[ -z "$PREPARE_SOURCE" ]]' in script
    assert any(s.get("name") == "Attest tarball" for s in steps)
    assert any(s.get("name") == "Store release evidence" for s in steps)

    for name in (
        "Attach evidence to GitHub Release",
        "Check if version already published",
        "Verify published tarball",
    ):
        item = next(s for s in steps if s.get("name") == name)
        assert item["if"] == "inputs.source_commit == ''"
    publication = next(s for s in steps if s.get("name") == "Publish to npm")
    assert publication["if"].startswith("inputs.source_commit == '' &&")
    assert "npm publish" in publication["run"]


@pytest.mark.skipif(os.name == "nt", reason="POSIX Bash fixture; workflow runs on Ubuntu")
@pytest.mark.parametrize(
    ("prepare", "match", "expect_ok", "expect_gh"),
    [
        (True, True, True, False),
        (False, True, True, True),
        (True, False, False, False),
    ],
)
def test_schema_source_verification_paths(
    tmp_path: Path, prepare: bool, match: bool, expect_ok: bool, expect_gh: bool
) -> None:
    step = next(s for s in _steps() if s.get("name") == "Verify immutable release source")
    sha = "a" * 40
    tag_sha = sha if match else "b" * 40
    scripts = tmp_path / "bin"
    scripts.mkdir()
    (scripts / "git").write_text(
        '#!/bin/sh\ncase "$1 $2" in\n'
        '  "rev-parse HEAD") echo ' + sha + ";;\n"
        '  "rev-list -n1") echo ' + tag_sha + ";;\n"
        "  *) exit 91;;\n"
        "esac\n",
        encoding="utf-8",
    )
    (scripts / "python").write_text("#!/bin/sh\necho 4.5.0\n", encoding="utf-8")
    gh_marker = tmp_path / "gh-used"
    (scripts / "gh").write_text(
        '#!/bin/sh\necho called > "$GH_MARKER"\necho "$RELEASE_TAG"\n', encoding="utf-8"
    )
    for path in scripts.iterdir():
        path.chmod(0o755)
    env = {
        **os.environ,
        "PATH": str(scripts) + os.pathsep + os.environ["PATH"],
        "RELEASE_TAG": "protocol-schemas-v4.5.0",
        "PREPARE_SOURCE": sha if prepare else "",
        "CALLER_SHA": sha,
        "GH_MARKER": str(gh_marker),
        "GITHUB_OUTPUT": str(tmp_path / "output"),
    }
    proc = subprocess.run(
        ["/bin/bash", "-euo", "pipefail", "-c", step["run"]],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert (proc.returncode == 0) is expect_ok, proc.stderr
    assert gh_marker.exists() is expect_gh
