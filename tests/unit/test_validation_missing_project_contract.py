"""Preserve errors when readiness and DRC state tools lack an active project."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace

import pytest

from kicad_mcp.tools import validation


@pytest.mark.parametrize(
    "invoke",
    [
        pytest.param(validation._release_artifact_evidence, id="release-artifacts"),
        pytest.param(validation._release_waiver_evidence, id="release-waivers"),
        pytest.param(validation._drc_state_path, id="drc-state-path"),
        pytest.param(
            lambda: validation._write_drc_state(Path("state.json"), {}),
            id="write-drc-state",
        ),
    ],
)
def test_project_is_required_before_release_or_drc_state_access(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    invoke: Callable[[], object],
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(validation, "get_config", lambda: SimpleNamespace(project_dir=None))

    with pytest.raises(ValueError, match=r"^No active project is configured\.$"):
        invoke()

    assert not (tmp_path / "state.json").exists()
    assert not (tmp_path / ".kicad-mcp").exists()


def test_release_artifact_readiness_requires_gerber_and_drill(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "output"
    output.mkdir()
    monkeypatch.setattr(
        validation, "get_config", lambda: SimpleNamespace(project_dir=tmp_path, output_dir=output)
    )
    for name in ("bom.csv", "board-pos.csv", "fabrication.pdf"):
        (output / name).write_text("placeholder", encoding="utf8")
    assert validation._release_artifact_evidence().available is False
    (output / "board.gbr").write_text("gerber", encoding="utf8")
    assert validation._release_artifact_evidence().available is False
    (output / "board.drl").write_text("drill", encoding="utf8")
    assert validation._release_artifact_evidence().available is True
