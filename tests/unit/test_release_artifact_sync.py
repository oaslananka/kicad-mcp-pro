from __future__ import annotations

import runpy
import sys
from functools import partial
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "release-please.yml"
SYNC_SCRIPT = ROOT / "scripts" / "sync_release_artifacts.py"


def test_release_please_uses_canonical_release_artifact_sync() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "scripts/sync_release_artifacts.py --write" in workflow
    assert "scripts/sync_mcp_metadata.py --write" not in workflow


def test_release_artifact_sync_covers_all_version_derived_outputs() -> None:
    assert SYNC_SCRIPT.is_file()
    script = SYNC_SCRIPT.read_text(encoding="utf-8")

    assert "sync_mcp_metadata" in script
    assert "build_tool_effect_manifest" in script


def _entrypoint_help(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    *,
    as_module: bool,
) -> str:
    # Exercise both Python entry modes without spawning an unneeded process.
    # A direct script launch puts its containing directory on sys.path.
    with monkeypatch.context() as patch:
        patch.setattr(sys, "argv", [str(SYNC_SCRIPT), "--help"])
        if not as_module:
            patch.syspath_prepend(str(SYNC_SCRIPT.parent))

        if as_module:
            run_entrypoint = partial(
                runpy.run_module,
                "scripts.sync_release_artifacts",
                run_name="__main__",
                alter_sys=True,
            )
        else:
            run_entrypoint = partial(runpy.run_path, str(SYNC_SCRIPT), run_name="__main__")
        with pytest.raises(SystemExit) as outcome:
            run_entrypoint()
        assert outcome.value.code == 0

    return capsys.readouterr().out


def test_release_artifact_sync_can_run_as_script(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert "--check" in _entrypoint_help(monkeypatch, capsys, as_module=False)


def test_release_artifact_sync_can_run_as_module(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert "--check" in _entrypoint_help(monkeypatch, capsys, as_module=True)
