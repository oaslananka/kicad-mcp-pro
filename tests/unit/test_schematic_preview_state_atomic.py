"""Partial preview/state writes cannot destroy the previous usable snapshot."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from kicad_mcp.tools import schematic


def test_atomic_state_write_preserves_prior_data_on_replace_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    destination = tmp_path / "state.json"
    destination.write_text('{"valid":true}', encoding="utf-8")
    original_replace = Path.replace

    def fail_replace(path: Path, target: Path) -> Path:
        if target == destination:
            raise OSError("simulated replace failure")
        return original_replace(path, target)

    monkeypatch.setattr(Path, "replace", fail_replace)
    with pytest.raises(OSError, match="simulated"):
        schematic._atomic_write_state(destination, '{"valid":false}')
    assert json.loads(destination.read_text(encoding="utf-8")) == {"valid": True}
    assert sorted(tmp_path.iterdir()) == [destination]


def test_preview_state_is_atomically_replaced_and_decodes(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(schematic, "get_config", lambda: SimpleNamespace(project_dir=tmp_path))
    schematic._schematic_live_preview_state_write("live.json", {"status": "ready"})
    assert schematic._schematic_live_preview_state_read("live.json") == {"status": "ready"}
    schematic._schematic_live_preview_state_write("live.json", {"status": "changed"})
    assert schematic._schematic_live_preview_state_read("live.json") == {"status": "changed"}


def test_corrupted_legacy_diff_state_is_not_treated_as_verified(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(schematic, "get_config", lambda: SimpleNamespace(project_dir=tmp_path))
    project = tmp_path / "sample.kicad_sch"
    state_name, _ = schematic._visual_diff_state_names(project)
    state_file = schematic._schematic_state_path(state_name)
    state_file.write_text('{"partial":', encoding="utf-8")
    assert schematic._load_schematic_visual_diff(project) is None
