"""A tag alone is not publication authority for the legacy Python workflow."""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def _workflow() -> dict:
    return yaml.safe_load((ROOT / ".github/workflows/publish-python.yml").read_text())


def test_release_guard_precedes_build_and_oidc_publication() -> None:
    jobs = _workflow()["jobs"]
    steps = jobs["build"]["steps"]
    guard = steps[1]
    assert guard["name"] == "Verify published release source"
    assert guard["if"] == "github.event_name == 'release'"
    assert "github.event.release.id" in guard["env"]["RELEASE_ID"]
    assert "github.sha" in guard["env"]["EXPECTED_SHA"]
    assert "github.ref" in guard["env"]["EXPECTED_REF"]
    assert "github.event.release.tag_name" in guard["env"]["RELEASE_TAG"]
    assert "github.event.release.draft == false" in jobs["build"]["if"]
    assert "github.event.release.draft == false" in jobs["publish-pypi"]["if"]
    assert "github.event_name == 'release'" in jobs["publish-pypi"]["if"]
    assert jobs["publish-pypi"]["needs"] == "build"
    assert jobs["publish-pypi"]["environment"]["name"] == "pypi"
    assert "github.event_name == 'workflow_dispatch'" in jobs["publish-testpypi"]["if"]
    assert "github.event_name == 'release'" not in jobs["publish-testpypi"]["if"]
