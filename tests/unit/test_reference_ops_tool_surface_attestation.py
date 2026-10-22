"""Tool attestation is a bounded, fail-closed, non-scoring handoff check."""

from pathlib import Path

import pytest

from scripts import attest_reference_ops_tool_surface as cli


@pytest.mark.parametrize(
    ("names", "matched"),
    [
        (["read", "write"], True),
        (["read"], False),
        (["read", "write", "unreviewed"], False),
        (["read", "write", "write"], False),
        ([], False),
    ],
)
def test_tool_allowlist_comparison(names: list[str], matched: bool) -> None:
    result = cli.compare_tools(names, {"read", "write"})
    assert result["matched"] is matched
    assert result["reviewed_count"] == 2
    assert result["observed_count"] == len(names)


def _ready(**_: object) -> dict[str, object]:
    return {
        "status": "handoff_required",
        "blocking_reasons": [],
        "attempt_id": "attempt-004",
        "source_revision": "a" * 40,
        "executes_agent": False,
        "counts_as_task_success": False,
    }


def _args(tmp_path: Path) -> dict[str, object]:
    return {
        "root": tmp_path,
        "board_id": "stm32f072-usbc",
        "attempt_number": 4,
        "phase_name": "schematic",
        "server_name": "kicad-msi-schematic-review",
        "config_path": tmp_path / "config.json",
    }


def _mock_preflight(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "preflight", _ready)
    monkeypatch.setattr(cli, "_read_ops_server_descriptor", lambda *_: {"env": {}})
    monkeypatch.setattr(cli, "_pinned_uv_version", lambda _: "0.12.19")
    monkeypatch.setattr(cli, "_ops_descriptor_matches", lambda *args: True)
    monkeypatch.setattr(
        cli, "reviewed_mcp_tools", lambda _: {"mcp__kicad__read", "mcp__kicad__write"}
    )


def test_good_live_list_is_not_a_task_success(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _mock_preflight(monkeypatch)

    async def collector(_: object) -> list[str]:
        return ["write", "read"]

    monkeypatch.setattr(cli, "list_live_tools", collector)
    result = cli.attest(**_args(tmp_path))
    assert result["status"] == "handoff_required"
    assert result["tool_surface_attested"] is True
    assert result["counts_as_task_success"] is False
    assert result["attempt_reserved"] is False
    assert result["executes_agent"] is False


@pytest.mark.parametrize(
    "names", [["read"], ["write", "read", "read"], ["read", "write", "unsafe"]]
)
def test_bad_tool_list_blocks(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, names: list[str]
) -> None:
    _mock_preflight(monkeypatch)

    async def collector(_: object) -> list[str]:
        return names

    monkeypatch.setattr(cli, "list_live_tools", collector)
    result = cli.attest(**_args(tmp_path))
    assert result["status"] == "blocked"
    assert result["blocking_reasons"] == ["reviewed_ops_tool_surface_mismatch"]


def test_preflight_block_never_calls_mcp(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _mock_preflight(monkeypatch)
    monkeypatch.setattr(
        cli, "preflight", lambda **_: {"status": "blocked", "blocking_reasons": ["source_mismatch"]}
    )

    async def collector(_: object) -> list[str]:
        raise AssertionError("MCP cannot be started on a failed offline preflight")

    monkeypatch.setattr(cli, "list_live_tools", collector)
    assert cli.attest(**_args(tmp_path))["blocking_reasons"] == ["source_mismatch"]


def test_unavailable_server_or_runtime_blocks(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _mock_preflight(monkeypatch)
    monkeypatch.setattr(cli, "_read_ops_server_descriptor", lambda *_: None)
    missing = cli.attest(**_args(tmp_path))
    assert missing["blocking_reasons"] == ["reviewed_ops_mcp_server_unavailable"]
    monkeypatch.setattr(cli, "_read_ops_server_descriptor", lambda *_: {"env": {}})

    async def unavailable(_: object) -> list[str]:
        raise OSError("host unavailable")

    monkeypatch.setattr(cli, "list_live_tools", unavailable)
    failed = cli.attest(**_args(tmp_path))
    assert failed["blocking_reasons"] == ["reviewed_ops_live_attestation_unavailable"]
    assert "host unavailable" not in str(failed)
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err == "live attestation failed: OSError\n"


def test_second_config_read_must_remain_reviewed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _mock_preflight(monkeypatch)
    monkeypatch.setattr(cli, "_ops_descriptor_matches", lambda *args: False)

    async def collector(_: object) -> list[str]:
        raise AssertionError("must not start a modified launcher")

    monkeypatch.setattr(cli, "list_live_tools", collector)
    result = cli.attest(**_args(tmp_path))
    assert result["status"] == "blocked"
    assert result["blocking_reasons"] == ["reviewed_ops_mcp_server_unavailable"]


@pytest.mark.parametrize(
    "unsafe_name",
    [
        "KICAD_API_SOCKET",
        "KICAD_MCP_KICAD_SOCKET_PATH",
        "KICAD_API_TOKEN",
        "KICAD_MCP_KICAD_TOKEN",
        "KICAD_MCP_REFERENCE_TRACE_PATH",
        "KICAD_MCP_REFERENCE_ATTEMPT_ID",
    ],
)
def test_live_inventory_must_reject_trace_or_socket_enabled_launchers(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, unsafe_name: str
) -> None:
    _mock_preflight(monkeypatch)
    monkeypatch.setattr(
        cli, "_read_ops_server_descriptor", lambda *_: {"env": {unsafe_name: "active"}}
    )

    async def collector(_: object) -> list[str]:
        raise AssertionError("tool listing must not start a recording/IPC session")

    monkeypatch.setattr(cli, "list_live_tools", collector)
    result = cli.attest(**_args(tmp_path))
    assert result["status"] == "blocked"
    assert result["blocking_reasons"] == ["reviewed_ops_mcp_server_unavailable"]
