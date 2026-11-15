"""Offline KiCad native-DRC preflight must never mutate a user's open PCB."""

from __future__ import annotations

from pathlib import Path

import pytest

from kicad_mcp.routing.manual_tracks import TrackSpec


def _candidate() -> list[TrackSpec]:
    return [TrackSpec(10.95, 10.0, 19.05, 10.0, "F_Cu", 0.25, "MID")]


def test_preflight_rejects_missing_project_rules(tmp_path: Path) -> None:
    from kicad_mcp.pcb.route_drc_preflight import RoutePreflightError, run_route_drc_preflight

    with pytest.raises(RoutePreflightError, match="project"):
        run_route_drc_preflight(
            "(kicad_pcb native snapshot)",
            _candidate(),
            project_file=tmp_path / "missing.kicad_pro",
            kicad_cli=tmp_path / "kicad-cli",
        )


def test_preflight_rejects_untrusted_candidate_geometry(tmp_path: Path) -> None:
    from kicad_mcp.pcb.route_drc_preflight import RoutePreflightError, run_route_drc_preflight

    pro = tmp_path / "demo.kicad_pro"
    pro.write_text('{"board":{}}', encoding="utf-8")
    cli = tmp_path / "kicad-cli"
    cli.write_text("fixture", encoding="utf-8")
    with pytest.raises(RoutePreflightError, match="width"):
        run_route_drc_preflight(
            "(kicad_pcb native snapshot)",
            [TrackSpec(0, 0, 1, 1, "F_Cu", 0, "MID")],
            project_file=pro,
            kicad_cli=cli,
        )


def test_preflight_rejects_absent_native_kicad_python(tmp_path: Path) -> None:
    from kicad_mcp.pcb.route_drc_preflight import RoutePreflightError, run_route_drc_preflight

    pro = tmp_path / "demo.kicad_pro"
    pro.write_text('{"board":{}}', encoding="utf-8")
    cli = tmp_path / "kicad-cli"
    cli.write_text("fixture", encoding="utf-8")
    with pytest.raises(RoutePreflightError, match="Python"):
        run_route_drc_preflight(
            "(kicad_pcb native snapshot)",
            _candidate(),
            project_file=pro,
            kicad_cli=cli,
        )


def test_preflight_keeps_custom_drc_rules_in_both_native_copies(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import re
    from types import SimpleNamespace

    from kicad_mcp.pcb import route_drc_preflight as module

    project = tmp_path / "demo.kicad_pro"
    rules = tmp_path / "demo.kicad_dru"
    project.write_text('{"board":{}}', encoding="utf-8")
    rules.write_text("(version 1) (rule sample)", encoding="utf-8")
    cli = tmp_path / "kicad-cli.exe"
    native_python = tmp_path / "python.exe"
    cli.write_text("fixture", encoding="utf-8")
    native_python.write_text("fixture", encoding="utf-8")
    inspected: list[bool] = []

    def fake_run(command: list[str], **_kwargs: object) -> SimpleNamespace:
        parent = Path(command[2]).parent
        inspected.append((parent / "demo.kicad_dru").read_text() == rules.read_text())
        return SimpleNamespace(returncode=0)

    before = {"violations": [], "unconnected_items": [{"id": "one"}]}
    after = {"violations": [], "unconnected_items": []}

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    def fake_drc(_cli: Path, board: Path, report: Path) -> dict[str, object]:
        if report.name == "rules-probe.json":
            rule_text = (board.parent / "demo.kicad_dru").read_text(encoding="utf-8")
            marker = re.search(r"KICAD_MCP_RULE_LOAD_SENTINEL_[0-9a-f]+", rule_text)
            assert marker is not None
            return {
                "violations": [
                    {
                        "type": "track_width",
                        "description": "Track width (rule '" + marker.group() + "')",
                        "severity": "error",
                    }
                ],
                "unconnected_items": [],
            }
        return before if board.parent.name == "baseline" else after

    monkeypatch.setattr(module, "_run_drc", fake_drc)
    result = module.run_route_drc_preflight(
        "(kicad_pcb test native board)",
        _candidate(),
        project_file=project,
        kicad_cli=cli,
    )
    assert result["accepted"] is True
    assert inspected == [True]


def test_native_preflight_pair_nets_are_explicitly_scoped() -> None:
    from kicad_mcp.pcb.route_drc_preflight import RoutePreflightError, _validate_specs

    plus = TrackSpec(10.95, 8.5, 19.05, 8.5, "F_Cu", 0.25, "USB_D_P")
    minus = TrackSpec(10.95, 9.25, 19.05, 9.25, "F_Cu", 0.25, "USB_D_N")
    with pytest.raises(RoutePreflightError, match="net"):
        _validate_specs([plus, minus])
    _validate_specs(
        [plus, minus],
        pair_nets=frozenset(("USB_D_P", "USB_D_N")),
    )
    with pytest.raises(RoutePreflightError, match="net"):
        _validate_specs(
            [plus, minus],
            pair_nets=frozenset(("USB_D_P", "MID")),
        )
