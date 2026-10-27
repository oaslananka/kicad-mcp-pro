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
