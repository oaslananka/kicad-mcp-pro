"""Ensure owner-invoked MCPB preparation never mutates a GitHub Release (#1179)."""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/publish-mcpb.yml"


def _config() -> dict:
    config = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    assert isinstance(config, dict)
    return config


def _steps() -> list[dict]:
    return _config()["jobs"]["publish"]["steps"]


def test_mcpb_prepare_interface_is_source_bound_and_legacy_events_remain() -> None:
    config = _config()
    events = config[True]  # PyYAML 1.1 parses GitHub Actions 'on' as True
    inputs = events["workflow_call"]["inputs"]
    assert set(inputs) == {"tag", "source_commit"}
    for definition in inputs.values():
        assert definition["required"] is True
        assert definition["type"] == "string"
    assert events["release"]["types"] == ["published"]
    assert "workflow_dispatch" in events

    job = config["jobs"]["publish"]
    condition = job["if"]
    assert "inputs.source_commit != ''" in condition
    assert "github.ref == 'refs/heads/main'" in condition
    assert "inputs.source_commit == ''" in condition
    assert "startsWith(inputs.tag, 'mcp-server-v')" in condition


def test_mcpb_prepare_attests_but_does_not_attach_to_release() -> None:
    steps = _steps()
    source_check = next(
        s for s in steps if s.get("name") == "Verify reusable preparation source identity"
    )
    assert source_check["if"] == "inputs.source_commit != ''"
    assert '[ "$CALLER_SHA" == "$EXPECTED_SOURCE" ]' in source_check["run"].replace(
        "[[", "["
    ).replace("]]", "]")
    assert "$(git rev-parse HEAD)" in source_check["run"]
    assert any(s.get("name") == "Attest MCPB bundle" for s in steps)
    assert any(s.get("name") == "Store MCPB release evidence" for s in steps)
    release_writes = [s for s in steps if "gh release upload" in s.get("run", "")]
    assert len(release_writes) == 1
    assert release_writes[0]["if"] == "inputs.source_commit == ''"
    assert "gh release create" not in WORKFLOW.read_text(encoding="utf-8")
    assert "gh release edit" not in WORKFLOW.read_text(encoding="utf-8")


def test_mcpb_tag_resolution_and_release_source_agree() -> None:
    steps = _steps()
    resolve = next(s for s in steps if s.get("name") == "Resolve release tag")
    assert resolve["env"]["PREPARE_SOURCE"] == "$" + "{{ inputs.source_commit }}"
    assert 'if [[ -n "$PREPARE_SOURCE" ]]' in resolve["run"]
    assert 'release_tag="$DISPATCH_TAG"' in resolve["run"]
    assert "Unsupported MCPB release tag" in resolve["run"]
    source_verify = next(
        s for s in steps if s.get("name") == "Verify release source and manifest version"
    )
    assert 'test "$source_commit" = "$tag_commit"' in source_verify["run"]
    assert 'test "$release_target" = "$source_commit"' in source_verify["run"]
