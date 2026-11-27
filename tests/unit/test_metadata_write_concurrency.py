from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest

from kicad_mcp.tools import simulation, variants


def test_parallel_variant_and_spice_updates_preserve_both_sections(
    tmp_path: Path, monkeypatch
) -> None:
    project = tmp_path / "project.kicad_pro"
    project.write_text('{"meta": {"version": 1}}', encoding="utf8")
    cfg = SimpleNamespace(project_file=project, project_dir=tmp_path)
    monkeypatch.setattr(variants, "get_config", lambda: cfg)
    monkeypatch.setattr(simulation, "get_config", lambda: cfg)
    read = simulation._read_project_json

    def slow_read():
        snapshot = read()
        time.sleep(0.1)
        return snapshot

    monkeypatch.setattr(simulation, "_read_project_json", slow_read)
    with ThreadPoolExecutor(max_workers=2) as pool:
        spice = pool.submit(simulation.sim_add_spice_library, "models", "models.lib")
        time.sleep(0.02)
        variant = pool.submit(variants.variant_create, "production")
        spice.result(timeout=5)
        variant.result(timeout=5)
    payload = json.loads(project.read_text(encoding="utf8"))
    assert "production" in payload["variants"]["variants"]
    assert payload["libraries"][0]["name"] == "models"
    assert payload["meta"] == {"version": 1}


def test_atomic_metadata_failure_preserves_original_and_cleans_temporary_file(
    tmp_path: Path, monkeypatch
) -> None:
    from kicad_mcp.utils.metadata_write import atomic_metadata_write

    project = tmp_path / "project.kicad_pro"
    project.write_text('{"original": true}', encoding="utf8")

    def fail_replace(_source: Path, _target: Path) -> Path:
        raise OSError("simulated publication failure")

    monkeypatch.setattr(Path, "replace", fail_replace)
    with pytest.raises(OSError, match="simulated publication failure"):
        atomic_metadata_write(project, '{"changed": true}')
    assert project.read_text(encoding="utf8") == '{"original": true}'
    assert list(tmp_path.iterdir()) == [project]


def test_metadata_write_replaces_link_entry_without_touching_unrelated_target(
    tmp_path: Path,
) -> None:
    from kicad_mcp.utils.metadata_write import atomic_metadata_write

    target = tmp_path / "unrelated"
    target.write_text("sentinel", encoding="utf8")
    link = tmp_path / "project.kicad_pro"
    try:
        link.symlink_to(target)
    except OSError as exc:
        pytest.skip(f"symlink unavailable: {exc}")
    atomic_metadata_write(link, '{"changed": true}')
    assert target.read_text(encoding="utf8") == "sentinel"
    assert not link.is_symlink()
    assert link.read_text(encoding="utf8") == '{"changed": true}'
