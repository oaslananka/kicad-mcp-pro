"""Unit tests for 3D model management tools (FAZ 7).
Tools: lib_bulk_assign_3d_models, lib_remove_3d_model,
lib_search_3d_models, lib_set_3d_model_path.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from kicad_mcp.errors import UnsafePathError
from kicad_mcp.server import create_server
from kicad_mcp.tools.three_d_models import (
    _find_3d_model_refs,
    _find_footprint_file,
    _search_3d_model_files,
    _write_footprint_text,
)
from kicad_mcp.utils.sexpr import _sexpr_string
from tests.conftest import call_tool_text


def test_find_footprint_file_not_found(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("KICAD_MCP_FOOTPRINT_LIBRARY_DIR", str(tmp_path))
    fp = _find_footprint_file("Missing", "Nonexistent")
    assert fp is None


def test_find_3d_model_refs_empty() -> None:
    refs = _find_3d_model_refs("(footprint (version 20250316))\n")
    assert refs == []


def test_find_3d_model_refs_single() -> None:
    text = '(footprint (version 20250316) (model "package.3dshapes/R.step"))\n'
    refs = _find_3d_model_refs(text)
    assert len(refs) == 1
    assert "R.step" in refs[0]["path"]


def test_search_3d_models_empty(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr("kicad_mcp.tools.three_d_models._footprint_3d_dir", lambda: tmp_path)
    results = _search_3d_model_files("R_0805")
    assert results == []


def test_find_footprint_file_rejects_library_parent_traversal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "footprints"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (outside / "Part.kicad_mod").write_text("(footprint)", encoding="utf-8")
    monkeypatch.setenv("KICAD_MCP_FOOTPRINT_LIBRARY_DIR", str(root))

    with pytest.raises(UnsafePathError):
        _find_footprint_file("../outside", "Part")


def test_find_footprint_file_rejects_footprint_path_separator(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "footprints"
    nested = root / "Outside"
    (root / "Library").mkdir(parents=True)
    nested.mkdir()
    (nested / "Part.kicad_mod").write_text("(footprint)", encoding="utf-8")
    monkeypatch.setenv("KICAD_MCP_FOOTPRINT_LIBRARY_DIR", str(root))

    with pytest.raises(UnsafePathError):
        _find_footprint_file("Library", "../Outside/Part")


def test_find_footprint_file_rejects_absolute_library(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "footprints"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (outside / "Part.kicad_mod").write_text("(footprint)", encoding="utf-8")
    monkeypatch.setenv("KICAD_MCP_FOOTPRINT_LIBRARY_DIR", str(root))

    with pytest.raises(UnsafePathError):
        _find_footprint_file(str(outside), "Part")


def test_find_footprint_file_rejects_foreign_windows_library_on_posix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    if os.name == "nt":
        pytest.skip("Foreign Windows path rejection is POSIX-specific.")
    root = tmp_path / "footprints"
    root.mkdir()
    monkeypatch.setenv("KICAD_MCP_FOOTPRINT_LIBRARY_DIR", str(root))

    with pytest.raises(UnsafePathError):
        _find_footprint_file(r"C:\\outside", "Part")


def test_find_footprint_file_rejects_library_symlink_escape(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "footprints"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (outside / "Part.kicad_mod").write_text("(footprint)", encoding="utf-8")
    link = root / "Linked"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlink unavailable: {exc}")
    monkeypatch.setenv("KICAD_MCP_FOOTPRINT_LIBRARY_DIR", str(root))

    with pytest.raises(UnsafePathError):
        _find_footprint_file("Linked", "Part")


def test_find_footprint_file_accepts_unicode_single_component_names(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "footprints"
    library = root / "My Library µ"
    library.mkdir(parents=True)
    expected = library / "Footprint Ω.kicad_mod"
    expected.write_text("(footprint)", encoding="utf-8")
    monkeypatch.setenv("KICAD_MCP_FOOTPRINT_LIBRARY_DIR", str(root))

    assert _find_footprint_file("My Library µ", "Footprint Ω") == expected.resolve()


@pytest.mark.anyio
async def test_bulk_assign_rejects_library_escape_before_writing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "footprints"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    footprint = outside / "Part.kicad_mod"
    original = "(footprint (version 20250316))\n"
    footprint.write_text(original, encoding="utf-8")
    monkeypatch.setenv("KICAD_MCP_FOOTPRINT_LIBRARY_DIR", str(root))
    server = create_server()

    result = await call_tool_text(
        server,
        "lib_bulk_assign_3d_models",
        {"library": "../outside", "footprint_pattern": ".*", "model_path": "evil.step"},
    )

    assert "traversal" in result.lower()
    assert footprint.read_text(encoding="utf-8") == original


@pytest.mark.anyio
async def test_bulk_assign_rejects_footprint_file_symlink_escape_before_writing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "footprints"
    library = root / "Library"
    outside = tmp_path / "outside.kicad_mod"
    library.mkdir(parents=True)
    original = "(footprint (version 20250316))\n"
    outside.write_text(original, encoding="utf-8")
    link = library / "Part.kicad_mod"
    try:
        link.symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"symlink unavailable: {exc}")
    monkeypatch.setenv("KICAD_MCP_FOOTPRINT_LIBRARY_DIR", str(root))
    server = create_server()

    result = await call_tool_text(
        server,
        "lib_bulk_assign_3d_models",
        {"library": "Library", "footprint_pattern": ".*", "model_path": "evil.step"},
    )

    assert "escapes workspace root" in result
    assert outside.read_text(encoding="utf-8") == original


@pytest.mark.anyio
async def test_bulk_assign_ignores_nonmatching_symlink_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "footprints"
    library = root / "Library"
    library.mkdir(parents=True)
    matching = library / "PartA.kicad_mod"
    matching.write_text("(footprint (version 20250316))\n", encoding="utf-8")
    outside = tmp_path / "outside.kicad_mod"
    outside.write_text("(footprint (version 20250316))\n", encoding="utf-8")
    ignored = library / "Ignored.kicad_mod"
    try:
        ignored.symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"symlink unavailable: {exc}")
    monkeypatch.setenv("KICAD_MCP_FOOTPRINT_LIBRARY_DIR", str(root))
    server = create_server()

    result = await call_tool_text(
        server,
        "lib_bulk_assign_3d_models",
        {"library": "Library", "footprint_pattern": "^PartA$", "model_path": "safe.step"},
    )

    assert result == "Updated 1 footprint(s) in library 'Library' with model 'safe.step'."
    assert "safe.step" in matching.read_text(encoding="utf-8")
    assert outside.read_text(encoding="utf-8") == "(footprint (version 20250316))\n"


def test_write_footprint_text_rejects_path_outside_library_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "footprints"
    root.mkdir()
    outside = tmp_path / "outside.kicad_mod"
    outside.write_text("original", encoding="utf-8")
    monkeypatch.setenv("KICAD_MCP_FOOTPRINT_LIBRARY_DIR", str(root))

    with pytest.raises(UnsafePathError):
        _write_footprint_text(outside, "changed")

    assert outside.read_text(encoding="utf-8") == "original"


@pytest.mark.anyio
async def test_set_3d_model_path_escapes_sexpr_string_input(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "footprints"
    library = root / "Library"
    library.mkdir(parents=True)
    footprint = library / "Part.kicad_mod"
    footprint.write_text("(footprint (version 20250316))\n", encoding="utf-8")
    monkeypatch.setenv("KICAD_MCP_FOOTPRINT_LIBRARY_DIR", str(root))
    server = create_server()
    malicious = 'safe.step")\n  (property "Injected" "yes")\n  (model "x'

    result = await call_tool_text(
        server,
        "lib_set_3d_model_path",
        {"library": "Library", "footprint": "Part", "model_path": malicious},
    )

    content = footprint.read_text(encoding="utf-8")
    assert "3D model set" in result
    assert f"(model {_sexpr_string(malicious)}" in content
    assert '\n  (property "Injected" "yes")' not in content


@pytest.mark.anyio
async def test_bulk_assign_escapes_sexpr_string_input(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "footprints"
    library = root / "Library"
    library.mkdir(parents=True)
    footprint = library / "Part.kicad_mod"
    footprint.write_text("(footprint (version 20250316))\n", encoding="utf-8")
    monkeypatch.setenv("KICAD_MCP_FOOTPRINT_LIBRARY_DIR", str(root))
    server = create_server()
    malicious = 'safe.step")\n  (property "Injected" "yes")\n  (model "x'

    result = await call_tool_text(
        server,
        "lib_bulk_assign_3d_models",
        {"library": "Library", "footprint_pattern": "^Part$", "model_path": malicious},
    )

    content = footprint.read_text(encoding="utf-8")
    assert "Updated 1 footprint" in result
    assert f"(model {_sexpr_string(malicious)}" in content
    assert '\n  (property "Injected" "yes")' not in content


@pytest.mark.anyio
async def test_set_3d_model_path_rejects_non_numeric_xyz_before_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "footprints"
    library = root / "Library"
    library.mkdir(parents=True)
    footprint = library / "Part.kicad_mod"
    original = "(footprint (version 20250316))\n"
    footprint.write_text(original, encoding="utf-8")
    monkeypatch.setenv("KICAD_MCP_FOOTPRINT_LIBRARY_DIR", str(root))
    server = create_server()

    result = await call_tool_text(
        server,
        "lib_set_3d_model_path",
        {
            "library": "Library",
            "footprint": "Part",
            "model_path": "safe.step",
            "offset_xyz": "0 0 0)(property",
        },
    )

    assert "must be three space-separated numbers" in result
    assert footprint.read_text(encoding="utf-8") == original


@pytest.mark.anyio
async def test_set_3d_model_path_replaces_escaped_model_path_cleanly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "footprints"
    library = root / "Library"
    library.mkdir(parents=True)
    footprint = library / "Part.kicad_mod"
    footprint.write_text("(footprint (version 20250316))\n", encoding="utf-8")
    monkeypatch.setenv("KICAD_MCP_FOOTPRINT_LIBRARY_DIR", str(root))
    server = create_server()
    malicious = 'safe.step")\n  (property "Injected" "yes")\n  (model "x'

    await call_tool_text(
        server,
        "lib_set_3d_model_path",
        {"library": "Library", "footprint": "Part", "model_path": malicious},
    )
    await call_tool_text(
        server,
        "lib_set_3d_model_path",
        {"library": "Library", "footprint": "Part", "model_path": "second.step"},
    )

    assert footprint.read_text(encoding="utf-8") == (
        '(footprint (version 20250316)\n  (model "second.step"\n  )\n)'
    )


@pytest.mark.anyio
async def test_bulk_assign_replaces_escaped_model_path_cleanly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "footprints"
    library = root / "Library"
    library.mkdir(parents=True)
    footprint = library / "Part.kicad_mod"
    footprint.write_text("(footprint (version 20250316))\n", encoding="utf-8")
    monkeypatch.setenv("KICAD_MCP_FOOTPRINT_LIBRARY_DIR", str(root))
    server = create_server()
    malicious = 'safe.step")\n  (property "Injected" "yes")\n  (model "x'

    await call_tool_text(
        server,
        "lib_set_3d_model_path",
        {"library": "Library", "footprint": "Part", "model_path": malicious},
    )
    await call_tool_text(
        server,
        "lib_bulk_assign_3d_models",
        {"library": "Library", "footprint_pattern": "^Part$", "model_path": "second.step"},
    )

    assert footprint.read_text(encoding="utf-8") == (
        '(footprint (version 20250316)\n  (model "second.step"\n  )\n)'
    )


@pytest.mark.anyio
async def test_remove_3d_model_matches_escaped_model_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "footprints"
    library = root / "Library"
    library.mkdir(parents=True)
    footprint = library / "Part.kicad_mod"
    footprint.write_text("(footprint (version 20250316))\n", encoding="utf-8")
    monkeypatch.setenv("KICAD_MCP_FOOTPRINT_LIBRARY_DIR", str(root))
    server = create_server()
    malicious = 'safe.step")\n  (property "Injected" "yes")\n  (model "x'

    await call_tool_text(
        server,
        "lib_set_3d_model_path",
        {"library": "Library", "footprint": "Part", "model_path": malicious},
    )
    result = await call_tool_text(
        server,
        "lib_remove_3d_model",
        {"library": "Library", "footprint": "Part", "model_path": malicious},
    )

    assert "Removed 1 3D model" in result
    assert "Injected" not in footprint.read_text(encoding="utf-8")
