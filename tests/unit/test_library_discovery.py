"""KiCad library-table (sym-lib-table / fp-lib-table) discovery (issue #78)."""

from __future__ import annotations

from pathlib import Path

import pytest

from kicad_mcp.tools.library import _parse_lib_table, _resolve_kicad_env


def test_resolve_kicad_env_substitutes_kiprjmod_and_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_dir = tmp_path / "proj"
    assert _resolve_kicad_env("${KIPRJMOD}/libs/X.kicad_sym", project_dir) == (
        f"{project_dir}/libs/X.kicad_sym"
    )
    monkeypatch.setenv("MY_LIB_DIR", "/opt/libs")
    assert _resolve_kicad_env("${MY_LIB_DIR}/X.kicad_sym", None) == "/opt/libs/X.kicad_sym"
    # An unknown variable is left untouched rather than expanded to empty.
    assert _resolve_kicad_env("${UNKNOWN_VAR_XYZ}/x", None) == "${UNKNOWN_VAR_XYZ}/x"


def test_parse_lib_table_resolves_kiprjmod_and_skips_non_kicad(tmp_path: Path) -> None:
    lib_dir = tmp_path / "libs"
    lib_dir.mkdir()
    sym = lib_dir / "ProjLib.kicad_sym"
    sym.write_text('(kicad_symbol_lib (symbol "R"))', encoding="utf-8")

    table = tmp_path / "sym-lib-table"
    table.write_text(
        "(sym_lib_table\n"
        '  (lib (name "ProjLib")(type "KiCad")'
        '(uri "${KIPRJMOD}/libs/ProjLib.kicad_sym")(options "")(descr ""))\n'
        '  (lib (name "Legacy")(type "Legacy")'
        '(uri "${KIPRJMOD}/libs/old.lib")(options "")(descr ""))\n'
        '  (lib (name "Missing")(type "KiCad")'
        '(uri "${KIPRJMOD}/libs/nope.kicad_sym")(options "")(descr ""))\n'
        ")",
        encoding="utf-8",
    )

    libs = _parse_lib_table(table, tmp_path)
    # KIPRJMOD-resolved KiCad lib is found; the Legacy type and the missing file are skipped.
    assert libs == {"ProjLib": sym}


def test_parse_lib_table_handles_unreadable_table(tmp_path: Path) -> None:
    assert _parse_lib_table(tmp_path / "does-not-exist", tmp_path) == {}


def test_shared_footprint_resolver_finds_project_table_entry(tmp_path: Path) -> None:
    from kicad_mcp.utils.library_tables import resolve_footprint_file

    project_dir = tmp_path / "project"
    pretty_dir = project_dir / "footprints" / "Gateway.pretty"
    pretty_dir.mkdir(parents=True)
    footprint = pretty_dir / "Custom.kicad_mod"
    footprint.write_text('(footprint "Custom")\n', encoding="utf-8")
    (project_dir / "fp-lib-table").write_text(
        '(fp_lib_table (lib (name "Gateway") (type "KiCad") '
        '(uri "${KIPRJMOD}/footprints/Gateway.pretty") (options "") (descr "")))\n',
        encoding="utf-8",
    )

    assert (
        resolve_footprint_file(
            "Gateway",
            "Custom",
            configured_root=None,
            project_dir=project_dir,
        )
        == footprint
    )


def test_shared_footprint_resolver_preserves_configured_root_fallback(tmp_path: Path) -> None:
    from kicad_mcp.utils.library_tables import resolve_footprint_file

    configured_root = tmp_path / "footprints"
    configured_root.mkdir()

    assert (
        resolve_footprint_file(
            "Resistor_SMD",
            "R_0805",
            configured_root=configured_root,
            project_dir=None,
        )
        == configured_root / "Resistor_SMD.pretty" / "R_0805.kicad_mod"
    )


def test_shared_footprint_resolver_rejects_unknown_library(tmp_path: Path) -> None:
    from kicad_mcp.utils.library_tables import resolve_footprint_file

    with pytest.raises(FileNotFoundError, match="fp-lib-table"):
        resolve_footprint_file(
            "Missing",
            "Unknown",
            configured_root=None,
            project_dir=tmp_path,
        )


def test_library_and_pcb_resolvers_return_same_project_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    from kicad_mcp.tools import library as library_mod
    from kicad_mcp.tools import pcb as pcb_mod

    project_dir = tmp_path / "project"
    pretty_dir = project_dir / "footprints" / "Gateway.pretty"
    pretty_dir.mkdir(parents=True)
    footprint = pretty_dir / "Custom.kicad_mod"
    footprint.write_text('(footprint "Custom")\n', encoding="utf-8")
    project_file = project_dir / "demo.kicad_pro"
    project_file.write_text("{}\n", encoding="utf-8")
    (project_dir / "fp-lib-table").write_text(
        '(fp_lib_table (lib (name "Gateway") (type "KiCad") '
        '(uri "${KIPRJMOD}/footprints/Gateway.pretty") (options "") (descr "")))\n',
        encoding="utf-8",
    )
    config = SimpleNamespace(
        project_file=project_file,
        project_dir=project_dir,
        footprint_library_dir=None,
    )
    monkeypatch.setattr("kicad_mcp.library_resolution.get_config", lambda: config)

    assert library_mod._footprint_file is pcb_mod._footprint_file
    assert library_mod._footprint_file("Gateway", "Custom") == footprint
    assert pcb_mod._footprint_file("Gateway", "Custom") == footprint


def test_active_project_dir_falls_back_to_project_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    from kicad_mcp.library_resolution import active_project_dir

    config = SimpleNamespace(project_file=None, project_dir=tmp_path)
    monkeypatch.setattr("kicad_mcp.library_resolution.get_config", lambda: config)

    assert active_project_dir() == tmp_path


def test_parse_lib_table_skips_entry_without_uri(tmp_path: Path) -> None:
    table = tmp_path / "fp-lib-table"
    table.write_text(
        '(fp_lib_table (lib (name "Broken") (type "KiCad")))\n',
        encoding="utf-8",
    )

    assert _parse_lib_table(table, tmp_path) == {}


def test_lib_table_paths_discovers_global_kicad_table(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kicad_mcp.utils.library_tables import lib_table_paths

    appdata = tmp_path / "appdata"
    table = appdata / "kicad" / "10.0" / "fp-lib-table"
    table.parent.mkdir(parents=True)
    table.write_text("(fp_lib_table)\n", encoding="utf-8")
    monkeypatch.setenv("APPDATA", str(appdata))

    assert table in lib_table_paths("fp-lib-table", project_dir=None)
