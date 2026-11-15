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


def test_preflight_rejects_malformed_board_without_native_python(tmp_path: Path) -> None:
    from kicad_mcp.pcb.route_drc_preflight import RoutePreflightError, run_route_drc_preflight

    project = tmp_path / "demo.kicad_pro"
    project.write_text('{"board":{}}', encoding="utf-8")
    cli = tmp_path / "kicad-cli"
    cli.write_text("fixture", encoding="utf-8")
    with pytest.raises(RoutePreflightError, match="candidate"):
        run_route_drc_preflight(
            "(kicad_pcb malformed",
            _candidate(),
            project_file=project,
            kicad_cli=cli,
        )


def test_preflight_keeps_custom_drc_rules_in_both_native_copies(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import re

    from kicad_mcp.pcb import route_drc_preflight as module

    project = tmp_path / "demo.kicad_pro"
    rules = tmp_path / "demo.kicad_dru"
    project.write_text('{"board":{}}', encoding="utf-8")
    rules.write_text("(version 1) (rule sample)", encoding="utf-8")
    cli = tmp_path / "kicad-cli.exe"
    cli.write_text("fixture", encoding="utf-8")
    inspected: list[bool] = []

    before = {"violations": [], "unconnected_items": [{"id": "one"}]}
    after = {"violations": [], "unconnected_items": []}

    def fake_drc(_cli: Path, board: Path, report: Path) -> dict[str, object]:
        if board.parent.name == "candidate" and report.name == "report.json":
            inspected.append((board.parent / "demo.kicad_dru").read_text() == rules.read_text())
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
        (
            Path(__file__).resolve().parents[1]
            / "fixtures"
            / "benchmark_projects"
            / "fail_dirty_transfer_wrong_pad_nets"
            / "demo.kicad_pcb"
        ).read_text(encoding="utf-8"),
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


def test_native_drc_invocation_preserves_argv_and_disables_shell(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An adversarial-looking filename must remain one inert argv element."""
    import json
    from types import SimpleNamespace

    from kicad_mcp.pcb import route_drc_preflight as module

    cli = tmp_path / "kicad-cli"
    board = tmp_path / "pcb; $(not-a-command).kicad_pcb"
    report = tmp_path / "drc report.json"
    calls: list[tuple[list[str], dict[str, object]]] = []

    def fake_run(command: list[str], **kwargs: object) -> SimpleNamespace:
        calls.append((command, kwargs))
        report.write_text(
            json.dumps(
                {
                    "violations": [],
                    "unconnected_items": [],
                    "included_severities": ["error"],
                    "ignored_checks": [],
                }
            ),
            encoding="utf-8",
        )
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    result = module._run_drc(cli, board, report)
    assert result["violations"] == []
    assert len(calls) == 1
    argv, options = calls[0]
    assert argv == [
        str(cli),
        "pcb",
        "drc",
        "--format",
        "json",
        "--output",
        str(report),
        str(board),
    ]
    assert options["shell"] is False
    assert options["timeout"] == 45
