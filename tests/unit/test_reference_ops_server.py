"""Runtime tool-surface boundaries for the opt-in reference ChatGPT–Ops host."""

from __future__ import annotations

import asyncio

import pytest

from kicad_mcp.config import reset_config
from kicad_mcp.evals.reference_agent_runner import (
    ReferenceAgentPhase,
    ReferenceAgentRunnerError,
    reviewed_mcp_tools,
)
from kicad_mcp.evals.reference_ops_server import build_reference_ops_server


@pytest.fixture(autouse=True)
def _isolate_phase_environment(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("KICAD_MCP_PROFILE", "schematic_authoring")
    monkeypatch.setenv("KICAD_MCP_OPERATING_MODE", "write")
    monkeypatch.setenv("KICAD_MCP_TRANSPORT", "stdio")
    reset_config()
    try:
        yield
    finally:
        reset_config()


def test_schematic_tools_are_exact_reviewed_allowlist_in_both_layers() -> None:
    server = build_reference_ops_server(phase_name="schematic")
    server.filter_runtime_tools = False
    exact = {
        name.removeprefix("mcp__kicad__")
        for name in reviewed_mcp_tools(ReferenceAgentPhase.for_name("schematic"))
    }
    names = {tool.name for tool in server.list_tools_sync()}
    assert len(exact) == 37
    assert names == exact
    assert server.allowed_tool_names == exact
    assert server.execution_tool_names == exact
    assert {"sch_get_wires", "sch_delete_wire"} <= names
    # Recovery access is intentionally narrow: no broad symbol deletion
    # or bypass of the reviewed phase API.
    assert "sch_delete_symbol" not in names
    assert "sch_move_symbol" not in names
    assert "drc_rule_delete" not in names


def test_nonreviewed_tool_is_rejected_at_execution_boundary() -> None:
    server = build_reference_ops_server(phase_name="schematic")
    result = asyncio.run(server.call_tool("drc_rule_delete", {"name": "UNREVIEWED"}))
    assert result.is_error is True
    assert "not available in this server execution surface" in str(result)
    assert result.structured_content is None


@pytest.mark.parametrize(
    ("profile", "operating_mode", "phase"),
    [
        ("review", "write", "schematic"),
        ("schematic_authoring", "readonly", "schematic"),
        ("schematic_authoring", "write", "manufacturing"),
        ("pcb_layout", "write", "schematic"),
    ],
)
def test_wrong_profile_or_phase_refuses_server(
    monkeypatch: pytest.MonkeyPatch, profile: str, operating_mode: str, phase: str
) -> None:
    monkeypatch.setenv("KICAD_MCP_PROFILE", profile)
    monkeypatch.setenv("KICAD_MCP_OPERATING_MODE", operating_mode)
    reset_config()
    with pytest.raises(ReferenceAgentRunnerError):
        build_reference_ops_server(phase_name=phase)


def test_entrypoint_starts_only_reviewed_stdio_server(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sys
    from types import SimpleNamespace

    from kicad_mcp.evals import reference_ops_server as cli

    observed: list[object] = []

    def guarded_run(**kwargs: object) -> None:
        import os
        from pathlib import Path

        private = os.environ.get("KICAD_MCP_KICAD_SOCKET_PATH")
        assert private is not None
        assert private.startswith("ipc://")
        endpoint = Path(private.removeprefix("ipc://"))
        assert endpoint.parent.is_dir()
        assert not endpoint.exists()
        assert endpoint.parent.name.startswith("kicad-reference-no-ambient-ipc-")
        observed.append(kwargs)

    fake_server = SimpleNamespace(run=guarded_run)
    monkeypatch.setattr(
        cli,
        "build_reference_ops_server",
        lambda *, phase_name: observed.append(phase_name) or fake_server,
    )
    monkeypatch.setattr(cli, "_ensure_thread_aware_stdout", lambda: observed.append("stdout"))
    monkeypatch.setattr(sys, "argv", ["reference_ops_server", "--phase", "schematic"])
    cli.main()
    assert observed == ["schematic", "stdout", {"transport": "stdio"}]


def test_entrypoint_blocks_non_stdio_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sys

    from kicad_mcp.evals import reference_ops_server as cli

    monkeypatch.setenv("KICAD_MCP_TRANSPORT", "streamable-http")
    monkeypatch.setattr(sys, "argv", ["reference_ops_server", "--phase", "schematic"])
    with pytest.raises(SystemExit, match="requires stdio transport"):
        cli.main()


def test_entrypoint_rejects_pcb_phase_before_live_gui_attachment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sys

    from kicad_mcp.evals import reference_ops_server as cli

    monkeypatch.setattr(sys, "argv", ["reference_ops_server", "--phase", "pcb"])
    with pytest.raises(SystemExit, match="separately attested isolated IPC transport"):
        cli.main()


def test_entrypoint_reports_runtime_gate_failure_without_starting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kicad_mcp.evals import reference_ops_server as cli

    def reject(*, phase_name: str) -> None:
        assert phase_name == "schematic"
        raise ReferenceAgentRunnerError("reviewed tool inventory unavailable")

    monkeypatch.setattr(cli, "build_reference_ops_server", reject)
    with pytest.raises(SystemExit, match="reviewed tool inventory unavailable"):
        cli.main(["--phase", "schematic"])


@pytest.mark.parametrize(
    "forbidden",
    ("KICAD_API_SOCKET", "KICAD_MCP_KICAD_SOCKET_PATH", "KICAD_API_TOKEN", "KICAD_MCP_KICAD_TOKEN"),
)
def test_reference_entrypoint_refuses_inherited_ipc_credentials(
    monkeypatch: pytest.MonkeyPatch, forbidden: str
) -> None:
    from kicad_mcp.evals import reference_ops_server as cli

    monkeypatch.setenv(forbidden, "unsafe-ambient")
    with pytest.raises(SystemExit, match="forbids inherited KiCad IPC credentials"):
        cli.main(["--phase", "schematic"])


def test_reference_pcb_phase_never_implicitly_attaches_live_gui() -> None:
    from kicad_mcp.evals import reference_ops_server as cli

    with pytest.raises(SystemExit, match="separately attested isolated IPC transport"):
        cli.main(["--phase", "pcb"])


def test_guarded_runtime_never_autodiscovers_host_socket() -> None:
    import os
    from pathlib import Path

    from kicad_mcp.config import get_config, reset_config
    from kicad_mcp.evals import reference_ops_server as cli

    with cli._guard_reference_runtime_ipc("schematic"):
        reset_config()
        cfg = get_config()
        endpoint = str(cfg.kicad_socket_path)
        assert endpoint.startswith("ipc://")
        private = Path(endpoint.removeprefix("ipc://"))
        assert private.parent.name.startswith("kicad-reference-no-ambient-ipc-")
        assert private.parent.is_dir()
        assert not private.exists()
        # A settings refresh must not silently revert to KiPy's default socket.
        reset_config()
        assert str(get_config().kicad_socket_path) == endpoint
    assert "KICAD_MCP_KICAD_SOCKET_PATH" not in os.environ
