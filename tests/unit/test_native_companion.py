"""Native IPC companion tests (no GUI, socket or external network required)."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages" / "kicad-plugin"))

from companion_core import (  # noqa: E402
    BoardSummary,
    backend_status,
    board_summary,
    dashboard_url,
    repair_ipc_dependencies,
    sync_board_context,
)
from context import CompanionHealthStatus  # noqa: E402


def test_ipc_summary_is_read_only(tmp_path: Path) -> None:
    board = Mock()
    board.name = "sample.kicad_pcb"
    board.get_project.return_value.name = "sample"
    board.get_project.return_value.path = str(tmp_path / "sample.kicad_pro")
    board.get_footprints.return_value = [1, 2]
    board.get_nets.return_value = [1, 2, 3]
    board.get_selection.return_value = []
    client = Mock()
    client.get_board.return_value = board

    result = board_summary(lambda: client)

    assert result.name == "sample.kicad_pcb"
    assert result.project == "sample"
    assert result.footprints == 2
    assert result.nets == 3
    assert result.selected == 0
    client.get_board.assert_called_once_with()
    board.get_selection.assert_called_once_with()


def test_saved_drc_uses_private_snapshot_no_cli_write_to_original(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import json
    from types import SimpleNamespace

    import companion_core

    board = tmp_path / "safe.kicad_pcb"
    board.write_text("board-bytes", encoding="utf-8")
    (tmp_path / "safe.kicad_pro").write_text("project-rules", encoding="utf-8")
    (tmp_path / "safe.kicad_dru").write_text("custom-rules", encoding="utf-8")
    source_files = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    summary = companion_core.BoardSummary(
        "safe.kicad_pcb", "safe", 1, 1, 0, str(tmp_path / "safe.kicad_pro")
    )

    def fake_cli(argv: list[str], **kwargs: object) -> SimpleNamespace:
        assert argv[:6] == ["kicad-cli", "pcb", "drc", "--format", "json", "--output"]
        copied = Path(argv[-1])
        assert copied != board and copied.read_bytes() == b"board-bytes"
        assert (copied.parent / "safe.kicad_pro").read_bytes() == b"project-rules"
        assert (copied.parent / "safe.kicad_dru").read_bytes() == b"custom-rules"
        assert "--save-board" not in argv and "--refill-zones" not in argv
        report = {
            "source": "safe.kicad_pcb",
            "kicad_version": "10.0.7",
            "violations": [
                {"severity": "error"},
                {"severity": "warning"},
            ],
            "unconnected_items": [{"severity": "error"}],
        }
        Path(argv[-2]).write_text(json.dumps(report), encoding="utf-8")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(companion_core.subprocess, "run", fake_cli)
    result = companion_core.run_saved_board_drc(summary)
    assert (result.errors, result.warnings, result.unconnected) == (1, 1, 1)
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir()} == source_files


def test_saved_drc_rejects_outside_project_path_and_cli_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import subprocess
    from types import SimpleNamespace

    import companion_core

    (tmp_path / "safe.kicad_pcb").write_text("board", encoding="utf-8")
    summary = companion_core.BoardSummary("../other.kicad_pcb", "demo", 1, 1, 0, str(tmp_path))
    with pytest.raises(RuntimeError, match="project directory"):
        companion_core.run_saved_board_drc(summary)
    summary = companion_core.BoardSummary("safe.kicad_pcb", "demo", 1, 1, 0, str(tmp_path))
    monkeypatch.setattr(
        companion_core.subprocess, "run", lambda *_a, **_kw: SimpleNamespace(returncode=1)
    )
    with pytest.raises(RuntimeError, match="complete DRC report"):
        companion_core.run_saved_board_drc(summary)

    def timeout(*_a: object, **_kw: object) -> None:
        raise subprocess.TimeoutExpired("kicad-cli", 45)

    monkeypatch.setattr(companion_core.subprocess, "run", timeout)
    with pytest.raises(RuntimeError, match="could not finish"):
        companion_core.run_saved_board_drc(summary)


def test_saved_drc_disallows_invalid_or_mismatched_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import json
    from types import SimpleNamespace

    import companion_core

    (tmp_path / "safe.kicad_pcb").write_text("board", encoding="utf-8")
    summary = companion_core.BoardSummary("safe.kicad_pcb", "demo", 1, 1, 0, str(tmp_path))

    def wrong_source(argv: list[str], **_kw: object) -> SimpleNamespace:
        Path(argv[-2]).write_text(
            json.dumps(
                {
                    "source": "other.kicad_pcb",
                    "kicad_version": "10.0.7",
                    "violations": [],
                    "unconnected_items": [],
                }
            ),
            encoding="utf-8",
        )
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(companion_core.subprocess, "run", wrong_source)
    with pytest.raises(RuntimeError, match="mismatched"):
        companion_core.run_saved_board_drc(summary)


def test_saved_drc_preserves_rule_item_coordinates_and_rejects_non_finite_positions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import json
    from types import SimpleNamespace

    import companion_core

    (tmp_path / "safe.kicad_pcb").write_text("board", encoding="utf-8")
    summary = companion_core.BoardSummary("safe.kicad_pcb", "demo", 1, 1, 0, str(tmp_path))

    def sample_cli(argv: list[str], **_kw: object) -> SimpleNamespace:
        Path(argv[-2]).write_text(
            json.dumps(
                {
                    "source": "safe.kicad_pcb",
                    "kicad_version": "10.0.7",
                    "coordinate_units": "mm",
                    "violations": [
                        {
                            "severity": "warning",
                            "type": "silk_over_copper",
                            "description": "Silkscreen overlap",
                            "items": [{"description": "Pad 1 of R1", "pos": {"x": "nan", "y": 2}}],
                        },
                        {
                            "severity": "error",
                            "type": "shorting_items",
                            "description": "Different nets shorted",
                            "items": [
                                {"description": "Pad 2 [GND] of R1", "pos": {"x": 11.5, "y": 9.25}}
                            ],
                        },
                    ],
                    "unconnected_items": [
                        {
                            "severity": "error",
                            "type": "unconnected_items",
                            "description": "Missing connection",
                            "items": [
                                {"description": "Track [LED_A] F.Cu", "pos": {"x": 12, "y": 10}}
                            ],
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(companion_core.subprocess, "run", sample_cli)
    result = companion_core.run_saved_board_drc(summary)
    assert len(result.findings) == 3
    assert [finding.check_type for finding in result.findings] == [
        "shorting_items",
        "unconnected_items",
        "silk_over_copper",
    ]
    assert result.findings[0].objects == ("Pad 2 [GND] of R1",)
    assert result.findings[0].location == (11.5, 9.25)
    assert result.findings[-1].location is None  # no invented coordinate
    assert result.coordinate_units == "mm"


def test_saved_drc_fails_closed_on_invalid_affected_item_structure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import json
    from types import SimpleNamespace

    import companion_core

    (tmp_path / "safe.kicad_pcb").write_text("board", encoding="utf-8")
    summary = companion_core.BoardSummary("safe.kicad_pcb", "demo", 1, 1, 0, str(tmp_path))

    def bad_cli(argv: list[str], **_kw: object) -> SimpleNamespace:
        Path(argv[-2]).write_text(
            json.dumps(
                {
                    "source": "safe.kicad_pcb",
                    "kicad_version": "10.0.7",
                    "violations": [{"severity": "error", "items": ["not-an-object"]}],
                    "unconnected_items": [],
                }
            ),
            encoding="utf-8",
        )
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(companion_core.subprocess, "run", bad_cli)
    with pytest.raises(RuntimeError, match="malformed affected items"):
        companion_core.run_saved_board_drc(summary)


def test_saved_drc_rejects_concurrently_changed_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import json
    from types import SimpleNamespace

    import companion_core

    board = tmp_path / "safe.kicad_pcb"
    board.write_text("original", encoding="utf-8")
    summary = companion_core.BoardSummary("safe.kicad_pcb", "demo", 1, 1, 0, str(tmp_path))

    def mutate_during_check(argv: list[str], **_kw: object) -> SimpleNamespace:
        Path(argv[-2]).write_text(
            json.dumps(
                {
                    "source": "safe.kicad_pcb",
                    "kicad_version": "10.0.7",
                    "violations": [],
                    "unconnected_items": [],
                }
            ),
            encoding="utf-8",
        )
        board.write_text("changed during CLI", encoding="utf-8")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(companion_core.subprocess, "run", mutate_during_check)
    with pytest.raises(RuntimeError, match="changed during DRC"):
        companion_core.run_saved_board_drc(summary)


def test_ipc_footprint_reference_field_is_used_for_selection(tmp_path: Path) -> None:
    """Actual kicad-python FootprintInstance exposes reference_field.text.value."""
    selected = Mock(spec=["reference_field"])
    selected.reference_field.text.value = "LED1"
    board = Mock()
    board.name = "live.kicad_pcb"
    board.get_project.return_value.name = "live"
    board.get_project.return_value.path = str(tmp_path / "live.kicad_pro")
    board.get_footprints.return_value = [selected]
    board.get_nets.return_value = [object()]
    board.get_selection.return_value = [selected]
    client = Mock()
    client.get_board.return_value = board
    result = board_summary(lambda: client)
    assert result.selected == 1
    assert result.selected_reference == "LED1"


def test_single_selected_footprint_inspector_reads_value_pads_and_net_names(tmp_path: Path) -> None:
    selected = Mock(spec=["reference_field", "value_field", "definition"])
    selected.reference_field.text.value = "R1"
    selected.value_field.text.value = "1k"
    selected.definition.id.library = "Resistor_SMD"
    selected.definition.id.name = "R_0603_1608Metric"
    pad1 = Mock()
    pad1.net.name = "LED_A"
    pad2 = Mock()
    pad2.net.name = ""
    selected.definition.pads = [pad1, pad2]
    board = Mock()
    board.name = "read-only.kicad_pcb"
    board.get_project.return_value.name = "demo"
    board.get_project.return_value.path = str(tmp_path / "demo")
    board.get_footprints.return_value = [selected]
    board.get_nets.return_value = [Mock()]
    board.get_selection.return_value = [selected]
    client = Mock()
    client.get_board.return_value = board

    result = board_summary(lambda: client)
    assert result.selected_reference == "R1"
    assert result.selected_value == "1k"
    assert result.selected_footprint == "Resistor_SMD:R_0603_1608Metric"
    assert result.selected_pad_count == 2
    assert result.selected_nets == ("LED_A",)
    assert result.selected_unconnected_pads == 1
    board.get_selection.assert_called_once_with()


def test_single_footprint_same_net_lists_other_references_without_routing_claims(
    tmp_path: Path,
) -> None:
    def footprint(ref: str, *net_names: str) -> Mock:
        item = Mock(spec=["reference_field", "definition"])
        item.reference_field.text.value = ref
        pads = []
        for name in net_names:
            pad = Mock()
            pad.net.name = name
            pads.append(pad)
        item.definition.pads = pads
        return item

    r1 = footprint("R1", "LED_A", "LED_A", "")
    led1 = footprint("LED1", "LED_A")
    c1 = footprint("C1", "GND")
    board = Mock()
    board.name = "clean-led.kicad_pcb"
    board.get_project.return_value.name = "clean-led"
    board.get_project.return_value.path = str(tmp_path / "clean-led.kicad_pro")
    board.get_footprints.return_value = [c1, led1, r1]
    board.get_nets.return_value = [Mock(), Mock()]
    board.get_selection.return_value = [r1]
    client = Mock()
    client.get_board.return_value = board

    summary = board_summary(lambda: client)
    assert summary.selected_reference == "R1"
    assert summary.selected_nets == ("LED_A",)
    assert summary.selected_net_peers == (("LED_A", ("LED1",)),)
    board.get_footprints.assert_called_once()


def test_same_net_peers_empty_for_unassigned_only_selection(tmp_path: Path) -> None:
    selected = Mock(spec=["reference_field", "definition"])
    selected.reference_field.text.value = "U1"
    pad = Mock()
    pad.net.name = ""
    selected.definition.pads = [pad]
    board = Mock()
    board.name = "floating.kicad_pcb"
    board.get_project.return_value.name = "floating"
    board.get_project.return_value.path = str(tmp_path / "floating.kicad_pro")
    board.get_footprints.return_value = [selected]
    board.get_nets.return_value = []
    board.get_selection.return_value = [selected]
    client = Mock()
    client.get_board.return_value = board

    assert board_summary(lambda: client).selected_net_peers == ()


def test_multiple_selection_does_not_show_first_footprint_as_sole_inspected_item(
    tmp_path: Path,
) -> None:
    board = Mock()
    board.name = "many.kicad_pcb"
    board.get_project.return_value.name = "demo"
    board.get_project.return_value.path = str(tmp_path / "demo")
    board.get_footprints.return_value = [Mock(), Mock()]
    board.get_nets.return_value = []
    a = Mock()
    b = Mock()
    a.reference_field.text.value = "R1"
    b.reference_field.text.value = "C1"
    board.get_selection.return_value = [a, b]
    client = Mock()
    client.get_board.return_value = board
    result = board_summary(lambda: client)
    assert result.selected == 2
    assert result.selected_reference == ""
    assert result.selected_footprint == ""
    assert result.selected_nets == ()
    assert result.selected_net_peers == ()


def test_unavailable_kicad_reports_failure() -> None:
    def disconnected() -> None:
        raise OSError("IPC disconnected")

    with pytest.raises(OSError, match="disconnected"):
        board_summary(disconnected)


def test_backend_status_uses_existing_health_contract() -> None:
    client = Mock()
    client.health.return_value = CompanionHealthStatus(
        "ready", "Backend is healthy and compatible.", "4.3.0"
    )
    factory = Mock(return_value=client)
    loader = Mock(return_value={"schema_version": "test"})

    ok, message = backend_status(client_factory=factory, compatibility_loader=loader)

    assert ok
    assert "healthy" in message
    assert factory.call_args.args == ("http://127.0.0.1:3334",)
    assert not factory.call_args.kwargs["auth_token"]
    client.health.assert_called_once_with({"schema_version": "test"})


def test_bad_backend_is_not_marked_ready() -> None:
    client = Mock()
    client.health.return_value = CompanionHealthStatus(
        "backend_unreachable", "Backend not reachable."
    )
    ok, message = backend_status(
        client_factory=lambda *_args, **_kwargs: client,
        compatibility_loader=lambda: {},
    )
    assert not ok
    assert "reachable" in message


def test_publish_context_uses_existing_mcp_client_contract(tmp_path: Path) -> None:
    client = Mock()
    client.health.return_value = CompanionHealthStatus("ready", "OK", "4.3.0")
    factory = Mock(return_value=client)
    snapshot = BoardSummary("board.kicad_pcb", "board", 3, 2, 1, str(tmp_path), "U1")

    sync_board_context(snapshot, client_factory=factory, compatibility_loader=lambda: {})

    args = client.push.call_args.args[0]
    assert args["file_type"] == "pcb"
    assert args["active_file"] == "board.kicad_pcb"
    assert args["selected_reference"] == "U1"
    assert args["snapshot"]["projectRoot"] == str(tmp_path)


def test_incompatible_backend_never_publishes_context() -> None:
    client = Mock()
    client.health.return_value = CompanionHealthStatus("backend_incompatible", "Mismatch")
    snapshot = BoardSummary("board.kicad_pcb", "board", 0, 0, 0)
    unavailable_factory = lambda *_args, **_kwargs: client  # noqa: E731
    loader = lambda: {}  # noqa: E731
    with pytest.raises(RuntimeError, match="Mismatch"):
        sync_board_context(
            snapshot,
            client_factory=unavailable_factory,
            compatibility_loader=loader,
        )
    client.push.assert_not_called()


def test_dashboard_is_loopback_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("KICAD_MCP_URL", raising=False)
    assert dashboard_url("#tools-catalog") == "http://127.0.0.1:3334/ui#tools-catalog"
    monkeypatch.setenv("KICAD_MCP_URL", "https://example.com")
    with pytest.raises(ValueError, match="loopback"):
        dashboard_url()


def test_dashboard_custom_local_port(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KICAD_MCP_URL", "http://localhost:3434")
    assert dashboard_url() == "http://localhost:3434/ui"


def test_repair_requires_kicad_private_environment(tmp_path: Path) -> None:
    requirements = tmp_path / "requirements.txt"
    requirements.write_text("kicad-python>=0.8,<1.0" + chr(10))
    runner = Mock()
    with pytest.raises(RuntimeError, match="virtual environment"):
        repair_ipc_dependencies(
            requirements_path=requirements,
            python_executable="/usr/bin/python3",
            in_virtualenv=False,
            runner=runner,
        )
    runner.assert_not_called()


def test_repair_uses_explicit_private_pip_and_disables_user_site(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    requirements = tmp_path / "requirements.txt"
    requirements.write_text("kicad-python>=0.8,<1.0" + chr(10))
    monkeypatch.setenv("PIP_USER", "1")
    runner = Mock()
    runner.return_value.returncode = 0
    repair_ipc_dependencies(
        requirements_path=requirements,
        python_executable="/private/venv/bin/python",
        in_virtualenv=True,
        runner=runner,
    )
    args, kwargs = runner.call_args
    assert args[0][:4] == ["/private/venv/bin/python", "-m", "pip", "install"]
    assert "--isolated" in args[0]
    assert "--require-virtualenv" in args[0]
    assert args[0][-2:] == ["-r", str(requirements)]
    assert kwargs["env"]["PYTHONNOUSERSITE"] == "1"
    assert "PIP_USER" not in kwargs["env"]
    assert kwargs["timeout"] == 180
    assert kwargs["check"] is False


def test_repair_failure_has_no_raw_pip_output_in_user_error(tmp_path: Path) -> None:
    requirements = tmp_path / "requirements.txt"
    requirements.write_text("kicad-python>=0.8,<1.0" + chr(10))
    runner = Mock()
    runner.return_value.returncode = 1
    runner.return_value.stderr = "secret environment context"
    with pytest.raises(RuntimeError, match="Check network access") as error:
        repair_ipc_dependencies(
            requirements_path=requirements,
            in_virtualenv=True,
            runner=runner,
        )
    assert "secret environment context" not in str(error.value)
