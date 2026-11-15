"""Security-critical fail-closed validation and native DRC evidence boundaries.

No KiCad executable is started: subprocess calls are replaced at the narrow
native adapter seam. Only disposable fixtures are read, never user projects.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from kicad_mcp.pcb import route_drc_preflight as preflight
from kicad_mcp.pcb.offline_route_tracks import render_candidate_board
from kicad_mcp.routing.manual_tracks import TrackSpec, ViaSpec

_FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "benchmark_projects"
    / "fail_dirty_transfer_wrong_pad_nets"
    / "demo.kicad_pcb"
)
_GOOD_TRACK = TrackSpec(10.95, 10, 19.05, 10, "F_Cu", 0.25, "MID")
_VIA_TRACKS = [
    TrackSpec(10.95, 10, 15, 10, "F_Cu", 0.25, "MID"),
    TrackSpec(15, 10, 19.05, 10, "B_Cu", 0.25, "MID"),
]
_GOOD_VIA = ViaSpec(15, 10, 0.8, 0.4, "MID")


@pytest.mark.parametrize(
    ("segments", "pair_nets", "via", "reason"),
    [
        ([], None, None, "1-128"),
        ([_GOOD_TRACK] * 129, None, None, "1-128"),
        ([replace(_GOOD_TRACK, net_name="")], None, None, "named net"),
        ([replace(_GOOD_TRACK, layer="F_SilkS")], None, None, "copper layer"),
        ([_GOOD_TRACK], frozenset(("MID",)), None, "two named nets"),
        ([_GOOD_TRACK], frozenset(("USB_P", "USB_N")), None, "two named nets"),
        ([_GOOD_TRACK], frozenset(("MID", "USB_N")), _GOOD_VIA, "Cannot combine"),
        (_VIA_TRACKS, None, replace(_GOOD_VIA, x_mm=float("nan")), "non-finite"),
        (_VIA_TRACKS, None, replace(_GOOD_VIA, drill_mm=0.9), "size or net"),
        (_VIA_TRACKS, None, replace(_GOOD_VIA, net_name="OTHER"), "size or net"),
        ([_GOOD_TRACK], None, _GOOD_VIA, "exactly two"),
        (_VIA_TRACKS, None, replace(_GOOD_VIA, x_mm=16), "endpoints"),
        ([replace(_GOOD_TRACK, x2_mm=float("inf"))], None, None, "non-finite"),
        ([replace(_GOOD_TRACK, width_mm=0)], None, None, "width"),
        ([_GOOD_TRACK, replace(_GOOD_TRACK, net_name="OTHER")], None, None, "mismatch"),
        ([_GOOD_TRACK, replace(_GOOD_TRACK, layer="B_Cu")], None, None, "mismatch"),
        ([_GOOD_TRACK, replace(_GOOD_TRACK, width_mm=0.3)], None, None, "mismatch"),
        ([replace(_GOOD_TRACK, x2_mm=10.95, y2_mm=10)], None, None, "Zero-length"),
        (
            [replace(_VIA_TRACKS[0], y1_mm=9.5), _VIA_TRACKS[1]],
            None,
            _GOOD_VIA,
            "H/V/45",
        ),
        (
            [replace(track, width_mm=1.0) for track in _VIA_TRACKS],
            None,
            _GOOD_VIA,
            "copper diameter",
        ),
        ([_GOOD_TRACK], frozenset(("MID", "USB_N")), None, "does not match"),
    ],
)
def test_preflight_refuses_unsafe_or_incomplete_route_geometry(
    segments: list[TrackSpec],
    pair_nets: frozenset[str] | None,
    via: ViaSpec | None,
    reason: str,
) -> None:
    with pytest.raises(preflight.RoutePreflightError, match=reason):
        preflight._validate_specs(segments, pair_nets=pair_nets, through_via=via)


@pytest.mark.parametrize(
    ("kind", "reason"),
    [
        ("oserror", "could not run"),
        ("timeout", "could not run"),
        ("cli_error", "did not complete"),
        ("missing", "did not complete"),
        ("invalid_json", "cannot be parsed"),
        ("invalid_schema", "invalid"),
        ("missing_connectivity", "did not verify connectivity"),
        ("ignored_unconnected", "did not verify connectivity"),
        ("missing_error_severity", "did not verify connectivity"),
    ],
)
def test_native_drc_fails_closed_on_runner_and_report_faults(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
    reason: str,
) -> None:
    cli = tmp_path / "kicad-cli"
    board = tmp_path / "demo.kicad_pcb"
    report = tmp_path / "report.json"

    def fake_run(argv: list[str], **kwargs: object) -> SimpleNamespace:
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
        assert kwargs["shell"] is False
        if kind == "oserror":
            raise OSError("native executable could not launch")
        if kind == "timeout":
            raise subprocess.TimeoutExpired(argv, timeout=45)
        if kind == "cli_error":
            return SimpleNamespace(returncode=1)
        if kind == "missing":
            return SimpleNamespace(returncode=0)
        if kind == "invalid_json":
            report.write_text("{", encoding="utf-8")
            return SimpleNamespace(returncode=0)
        if kind == "invalid_schema":
            report.write_text("[]", encoding="utf-8")
            return SimpleNamespace(returncode=0)

        payload: dict[str, object] = {
            "violations": [],
            "unconnected_items": [],
            "included_severities": ["error", "warning"],
            "ignored_checks": [],
        }
        if kind == "missing_connectivity":
            payload.pop("unconnected_items")
        if kind == "ignored_unconnected":
            payload["ignored_checks"] = [{"key": "unconnected_items"}]
        if kind == "missing_error_severity":
            payload["included_severities"] = ["warning"]
        report.write_text(json.dumps(payload), encoding="utf-8")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(preflight.subprocess, "run", fake_run)
    with pytest.raises(preflight.RoutePreflightError, match=reason):
        preflight._run_drc(cli, board, report)


def test_custom_rule_probe_refuses_native_report_without_marker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rules = tmp_path / "demo.kicad_dru"
    rules.write_text("(version 1)\n", encoding="utf-8")
    board = tmp_path / "demo.kicad_pcb"
    cli = tmp_path / "kicad-cli"
    monkeypatch.setattr(
        preflight,
        "_run_drc",
        lambda *_args: {
            "violations": [
                {
                    "type": "track_width",
                    "severity": "error",
                    "description": "Unrelated track width violation",
                }
            ],
            "unconnected_items": [],
        },
    )
    with pytest.raises(preflight.RoutePreflightError, match="rule loading"):
        preflight._validate_native_custom_rule_loading(cli, board, rules)
    assert re.search(r"KICAD_MCP_RULE_LOAD_SENTINEL_[0-9a-f]+", rules.read_text())


@pytest.mark.parametrize(
    ("source", "segments", "via", "reason"),
    [
        ("not a PCB", [_GOOD_TRACK], None, "board"),
        ("(kicad_pcb", [_GOOD_TRACK], None, "Malformed"),
        ("(kicad_pcb (not-closed", [_GOOD_TRACK], None, "Malformed"),
        ("(kicad_pcb nope)", [], None, "segment count"),
        ("(kicad_pcb nope)", [_GOOD_TRACK] * 129, None, "segment count"),
        (None, [_GOOD_TRACK], None, "board"),
    ],
)
def test_offline_candidate_rejects_malformed_or_unbounded_board(
    source: str | None,
    segments: list[TrackSpec],
    via: ViaSpec | None,
    reason: str,
) -> None:
    with pytest.raises(ValueError, match=reason):
        render_candidate_board(source, segments, via)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("tracks", "via", "reason"),
    [
        ([_GOOD_TRACK], None, ""),
        ([replace(_GOOD_TRACK, width_mm=-0.5)], None, "width"),
        ([replace(_GOOD_TRACK, width_mm=5.5)], None, "width"),
        (_VIA_TRACKS[:1], _GOOD_VIA, "join"),
        ([replace(_VIA_TRACKS[0], layer="B_Cu"), _VIA_TRACKS[1]], _GOOD_VIA, "join"),
        ([replace(_VIA_TRACKS[0], net_name="VIN"), _VIA_TRACKS[1]], _GOOD_VIA, "join"),
        (_VIA_TRACKS, replace(_GOOD_VIA, x_mm=14.8), "join"),
        (_VIA_TRACKS, replace(_GOOD_VIA, y_mm=10.5), "join"),
        (_VIA_TRACKS, replace(_GOOD_VIA, net_name="OTHER"), "join"),
        (_VIA_TRACKS, replace(_GOOD_VIA, drill_mm=float("nan")), "finite"),
        (_VIA_TRACKS, replace(_GOOD_VIA, diameter_mm=0.3), "invalid"),
    ],
)
def test_offline_candidate_cannot_append_unvalidated_geometry(
    tracks: list[TrackSpec],
    via: ViaSpec | None,
    reason: str,
) -> None:
    source = _FIXTURE.read_text(encoding="utf-8")
    if reason == "":
        candidate = render_candidate_board(source, tracks, via)
        assert "(segment" in candidate and "(via" not in candidate
    else:
        with pytest.raises(ValueError, match=reason):
            render_candidate_board(source, tracks, via)
    assert _FIXTURE.read_text(encoding="utf-8") == source


def test_preflight_refuses_invalid_project_cli_board_and_custom_rule_path(tmp_path: Path) -> None:
    project = tmp_path / "demo.kicad_pro"
    project.write_text("{}", encoding="utf-8")
    cli = tmp_path / "kicad-cli"
    cli.write_text("test", encoding="utf-8")
    board = _FIXTURE.read_text(encoding="utf-8")

    with pytest.raises(preflight.RoutePreflightError, match="project rules"):
        preflight.run_route_drc_preflight(
            board, [_GOOD_TRACK], project_file=tmp_path / "demo.txt", kicad_cli=cli
        )
    with pytest.raises(preflight.RoutePreflightError, match="executable"):
        preflight.run_route_drc_preflight(
            board,
            [_GOOD_TRACK],
            project_file=project,
            kicad_cli=tmp_path / "missing-cli",
        )
    with pytest.raises(preflight.RoutePreflightError, match="snapshot"):
        preflight.run_route_drc_preflight(
            "bad snapshot", [_GOOD_TRACK], project_file=project, kicad_cli=cli
        )

    (tmp_path / "demo.kicad_dru").mkdir()
    with pytest.raises(preflight.RoutePreflightError, match="rules path"):
        preflight.run_route_drc_preflight(board, [_GOOD_TRACK], project_file=project, kicad_cli=cli)
