from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path
from typing import Any

import anyio
import pytest
from mcp.types import CallToolResult
from starlette.testclient import TestClient

from kicad_mcp.config import get_config, reset_config
from kicad_mcp.discovery import CliCapabilities
from kicad_mcp.server import CLI_FAILURE_TOOL_NAMES, HEAVY_TOOL_NAMES, build_server
from tests.conftest import call_tool_text


def test_stateful_http_config_controls_fastmcp_setting(sample_project: Path) -> None:
    _ = sample_project
    cfg = get_config()
    cfg.stateful_http = True
    assert build_server("minimal").settings.stateless_http is False

    reset_config()
    cfg = get_config()
    cfg.stateful_http = False
    assert build_server("minimal").settings.stateless_http is True


@pytest.mark.anyio
async def test_metrics_increment_after_tool_call(sample_project: Path) -> None:
    _ = sample_project
    cfg = get_config()
    cfg.transport = "streamable-http"
    cfg.enable_metrics = True
    server = build_server("minimal")

    await call_tool_text(server, "kicad_get_version", {})

    response = TestClient(server.streamable_http_app()).get("/metrics")

    assert response.status_code == 200
    assert 'kicad_mcp_tool_calls_total{tool="kicad_get_version",status="ok"}' in response.text
    assert "kicad_mcp_tool_latency_p95_ms" in response.text


@pytest.mark.anyio
async def test_heavy_tool_calls_are_rate_limited(sample_project: Path, monkeypatch) -> None:
    _ = sample_project
    server = build_server("full")
    active = 0
    max_active = 0

    async def fake_call_tool(
        name: str,
        arguments: dict[str, Any],
        context: object | None = None,
        convert_result: bool = False,
    ) -> list[object]:
        nonlocal active, max_active
        _ = name, arguments, context, convert_result
        active += 1
        max_active = max(max_active, active)
        await anyio.sleep(0.05)
        active -= 1
        return []

    monkeypatch.setattr(server._tool_manager, "call_tool", fake_call_tool)

    await asyncio.gather(
        server.call_tool("export_gerber", {}),
        server.call_tool("export_gerber", {}),
        server.call_tool("export_gerber", {}),
    )

    assert max_active == 2


def test_release_heavy_tools_are_rate_limited() -> None:
    expected = {
        "run_drc",
        "run_erc",
        "project_quality_gate",
        "check_design_for_manufacture",
        "export_gerber",
        "pcb_export_3d_pdf",
        "export_manufacturing_package",
        "route_export_dsn",
        "route_autoroute_freerouting",
        "route_import_ses",
    }

    assert expected.issubset(HEAVY_TOOL_NAMES)


def test_cli_failure_tools_are_structured_error_candidates() -> None:
    expected = {
        "run_drc",
        "run_erc",
        "export_gerber",
        "get_board_stats",
        "pcb_export_3d_pdf",
        "route_autoroute_freerouting",
        "route_import_ses",
    }

    assert expected.issubset(CLI_FAILURE_TOOL_NAMES)


def test_audit_log_records_keys_without_sensitive_values(monkeypatch) -> None:
    from kicad_mcp import server as server_module

    cfg = get_config()
    cfg.transport = "streamable-http"
    events: list[tuple[str, dict[str, object]]] = []
    monkeypatch.setattr(
        server_module.logger,
        "info",
        lambda event, **kwargs: events.append((event, kwargs)),
    )

    server_module._audit_tool_call(
        tool_name="example_tool",
        arguments={"auth_token": "super-secret", "normal": "value"},
        status="ok",
        elapsed_ms=1.0,
        error_code=None,
    )

    assert events[0][1]["argument_keys"] == ["auth_token", "normal"]
    assert "super-secret" not in str(events[0])


@pytest.mark.anyio
async def test_http_tool_call_audit_log_is_emitted(sample_project: Path, monkeypatch) -> None:
    _ = sample_project
    cfg = get_config()
    cfg.transport = "streamable-http"
    server = build_server("minimal")
    events: list[tuple[str, dict[str, object]]] = []
    monkeypatch.setattr(
        "kicad_mcp.server.logger.info",
        lambda event, **kwargs: events.append((event, kwargs)),
    )

    await call_tool_text(server, "kicad_get_version", {})

    audit = [item for item in events if item[0] == "tool_call_audit"]
    assert audit
    assert audit[0][1]["tool"] == "kicad_get_version"
    assert audit[0][1]["status"] == "ok"


def test_token_rotation_requires_current_bearer_and_updates_verifier(sample_project: Path) -> None:
    _ = sample_project
    cfg = get_config()
    cfg.transport = "streamable-http"
    cfg.auth_token = "old-token"  # noqa: S105
    server = build_server("minimal")
    client = TestClient(server.streamable_http_app())

    unauthorized = client.post(
        "/.well-known/mcp-server/token-rotate",
        json={"new_token": "new-token"},
    )
    assert unauthorized.status_code == 401

    rotated = client.post(
        "/.well-known/mcp-server/token-rotate",
        headers={"Authorization": "Bearer old-token"},
        json={"new_token": "new-token"},
    )

    assert rotated.status_code == 200
    assert cfg.auth_token == "new-token"  # noqa: S105
    assert asyncio.run(server._token_verifier.verify_token("old-token")) is None
    assert asyncio.run(server._token_verifier.verify_token("new-token")) is not None


def test_http_mcp_endpoint_requires_bearer_token(sample_project: Path) -> None:
    _ = sample_project
    cfg = get_config()
    cfg.transport = "streamable-http"
    cfg.auth_token = "required-token"  # noqa: S105
    server = build_server("minimal")
    client = TestClient(server.streamable_http_app())

    response = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
    )

    assert response.status_code == 401
    assert response.json()["error"] == "invalid_token"


def test_token_rotation_rejects_non_string_token(sample_project: Path) -> None:
    _ = sample_project
    cfg = get_config()
    cfg.transport = "streamable-http"
    cfg.auth_token = "old-token"  # noqa: S105
    server = build_server("minimal")
    client = TestClient(server.streamable_http_app())

    response = client.post(
        "/.well-known/mcp-server/token-rotate",
        headers={"Authorization": "Bearer old-token"},
        json={"new_token": 123},
    )

    assert response.status_code == 400
    assert cfg.auth_token == "old-token"  # noqa: S105


@pytest.mark.anyio
async def test_tool_exception_returns_structured_error() -> None:
    server = build_server("full")

    result = await server.call_tool("export_gerber", {})

    assert isinstance(result, CallToolResult)
    assert result.isError is True
    assert result.structuredContent is not None
    assert result.structuredContent["error_code"] == "CONFIGURATION_ERROR"
    assert "message" in result.structuredContent
    assert "hint" in result.structuredContent


@pytest.mark.anyio
async def test_cli_nonzero_result_returns_structured_error(
    sample_project: Path,
    monkeypatch,
) -> None:
    class Result:
        returncode = 2
        stdout = ""
        stderr = "fatal export failed"

    monkeypatch.setattr(
        "kicad_mcp.tools.export.get_cli_capabilities",
        lambda _cli: CliCapabilities(
            version="KiCad 10.0.1",
            gerber_command="gerber",
            drill_command="drill",
            position_command="pos",
            supports_ipc2581=True,
        ),
    )
    monkeypatch.setattr("kicad_mcp.tools.export.subprocess.run", lambda *_args, **_kwargs: Result())

    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})
    result = await server.call_tool("export_gerber", {})

    assert isinstance(result, CallToolResult)
    assert result.isError is True
    assert result.structuredContent is not None
    assert result.structuredContent["error_code"] == "CLI_COMMAND_FAILED"
    assert "Gerber export failed" in result.structuredContent["message"]


@pytest.mark.anyio
async def test_export_gerber_sends_progress_notifications(
    sample_project: Path,
    monkeypatch,
) -> None:
    progress_events: list[tuple[float, float, str]] = []

    async def fake_report_progress(
        _ctx: object,
        progress: float,
        total: float,
        message: str,
    ) -> None:
        progress_events.append((progress, total, message))

    def fake_run_cli_variants(variants: list[list[str]]) -> tuple[int, str, str]:
        command = variants[0]
        output_index = command.index("--output") + 1
        output_path = Path(command[output_index])
        output_path.mkdir(parents=True, exist_ok=True)
        (output_path / "board-F_Cu.gbr").write_text("gerber\n", encoding="utf-8")
        return 0, "", ""

    monkeypatch.setattr("kicad_mcp.tools.export._report_progress", fake_report_progress)
    monkeypatch.setattr("kicad_mcp.tools.export._run_cli_variants", fake_run_cli_variants)
    monkeypatch.setattr(
        "kicad_mcp.tools.export.get_cli_capabilities",
        lambda _cli: CliCapabilities(
            version="KiCad 10.0.1",
            gerber_command="gerber",
            drill_command="drill",
            position_command="pos",
            supports_ipc2581=True,
        ),
    )

    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})
    result = await call_tool_text(server, "export_gerber", {})

    assert "Gerber export completed" in result
    assert progress_events[0][0:2] == (5, 100)
    assert progress_events[-1][0:2] == (100, 100)


@pytest.mark.anyio
async def test_manufacturing_gate_block_returns_structured_validation_error(
    sample_project: Path,
    monkeypatch,
) -> None:
    from kicad_mcp.tools.validation import GateOutcome

    monkeypatch.setattr(
        "kicad_mcp.tools.validation._evaluate_project_gate",
        lambda **_kwargs: [
            GateOutcome(name="DRC", status="FAIL", summary="DRC failed", details=["clearance"])
        ],
    )

    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})
    result = await server.call_tool("export_manufacturing_package", {})

    assert isinstance(result, CallToolResult)
    assert result.isError is True
    assert result.structuredContent is not None
    assert result.structuredContent["error_code"] == "VALIDATION_FAILED"


def test_run_cli_retries_transient_timeout(fake_cli: Path, monkeypatch) -> None:
    from kicad_mcp.tools import export

    attempts = 0

    def fake_run(*_args: object, **_kwargs: object):
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise subprocess.TimeoutExpired(cmd="kicad-cli", timeout=0.1)

        class Result:
            returncode = 0
            stdout = "ok"
            stderr = ""

        return Result()

    monkeypatch.setattr(export.subprocess, "run", fake_run)
    monkeypatch.setattr(export.time, "sleep", lambda _seconds: None)

    code, stdout, stderr = export._run_cli("pcb", "export", "gerber")

    assert (code, stdout, stderr) == (0, "ok", "")
    assert attempts == 3


def test_run_cli_does_not_retry_non_transient_exit(fake_cli: Path, monkeypatch) -> None:
    from kicad_mcp.tools import export

    attempts = 0

    def fake_run(*_args: object, **_kwargs: object):
        nonlocal attempts
        attempts += 1

        class Result:
            returncode = 2
            stdout = ""
            stderr = "syntax error"

        return Result()

    monkeypatch.setattr(export.subprocess, "run", fake_run)
    monkeypatch.setattr(export.time, "sleep", lambda _seconds: None)

    code, stdout, stderr = export._run_cli("pcb", "export", "gerber")

    assert (code, stdout, stderr) == (2, "", "syntax error")
    assert attempts == 1


def test_pdn_mesh_reports_ac_impedance_violations() -> None:
    from kicad_mcp.utils.pdn_mesh import PdnDecouplingCap, PdnLoad, PdnMesh

    result = PdnMesh().solve(
        net_name="+3V3",
        source_ref="U_REG",
        loads=[PdnLoad(ref="U1", current_a=0.2, distance_mm=50.0)],
        trace_width_mm=0.25,
        copper_weight_oz=1.0,
        nominal_voltage_v=3.3,
        frequency_points_hz=[1_000_000.0, 100_000_000.0],
        decoupling_caps=[
            PdnDecouplingCap(ref="C1", capacitance_f=100e-9, esr_ohm=0.02, esl_h=1e-9)
        ],
        target_impedance_ohm=0.05,
    )

    assert result.impedance_ohm
    assert result.max_impedance_ohm > 0.0
    assert result.impedance_violations


def test_release_workflow_uses_scoped_github_publish_secrets() -> None:
    workflow = (
        Path(__file__).resolve().parents[2] / ".github" / "workflows" / "release.yml"
    ).read_text(encoding="utf-8")

    assert "Verify required release secrets" in workflow
    assert "PYPI_TOKEN: ${{ secrets.PYPI_TOKEN }}" in workflow
    assert "TEST_PYPI_TOKEN: ${{ secrets.TEST_PYPI_TOKEN }}" in workflow
    assert "bash scripts/publish.sh" in workflow
    assert "doppler run --project all --config main -- bash scripts/publish.sh" not in workflow


def test_release_workflow_installs_actionlint_before_ci_check() -> None:
    workflow = (
        Path(__file__).resolve().parents[2] / ".github" / "workflows" / "release.yml"
    ).read_text(encoding="utf-8")

    setup_index = workflow.index("actions/setup-go@")
    install_index = workflow.index("Install workflow lint tools")
    check_index = workflow.index("corepack npm run check:ci")

    assert setup_index < install_index < check_index
    assert "go install github.com/rhysd/actionlint/cmd/actionlint@v1.7.7" in workflow
    assert 'echo "${HOME}/go/bin" >> "${GITHUB_PATH}"' in workflow


def test_release_please_uses_service_token_for_release_prs() -> None:
    workflow = (
        Path(__file__).resolve().parents[2] / ".github" / "workflows" / "release-please.yml"
    ).read_text(encoding="utf-8")

    assert "permissions:\n  contents: read" in workflow
    assert "contents: write" in workflow
    assert "pull-requests: write" in workflow
    assert "token: ${{ secrets.DOPPLER_GITHUB_SERVICE_TOKEN || github.token }}" in workflow


def test_docs_workflow_mirrors_canonical_pages_site() -> None:
    workflow = (
        Path(__file__).resolve().parents[2] / ".github" / "workflows" / "docs.yml"
    ).read_text(encoding="utf-8")

    assert "Mirror canonical GitHub Pages" in workflow
    assert "CANONICAL_PAGES_TOKEN: ${{ secrets.DOPPLER_GITHUB_SERVICE_TOKEN }}" in workflow
    assert "https://oaslananka.github.io/kicad-mcp-pro" in workflow
    assert "https://github.com/oaslananka/kicad-mcp-pro.git" in workflow
    assert "|| true" not in workflow


@pytest.mark.anyio
async def test_project_generate_design_prompt_uses_design_intent(sample_project: Path) -> None:
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})
    await call_tool_text(
        server,
        "project_set_design_intent",
        {
            "critical_nets": ["USB_DP", "USB_DN"],
            "manufacturer": "JLCPCB",
            "manufacturer_tier": "standard",
            "power_rails": [
                {
                    "name": "+3V3",
                    "voltage_v": 3.3,
                    "current_max_a": 0.5,
                    "source_ref": "U_REG",
                }
            ],
        },
    )

    prompt = await call_tool_text(
        server,
        "project_generate_design_prompt",
        {"circuit_description": "USB sensor", "target_fab": ""},
    )

    assert "USB sensor" in prompt
    assert "USB_DP, USB_DN" in prompt
    assert "+3V3" in prompt
    assert "jlcpcb_standard" in prompt.lower()


@pytest.mark.anyio
async def test_tune_track_length_emits_user_warning(sample_project: Path, mock_board) -> None:
    _ = mock_board
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    with pytest.warns(UserWarning, match="tune_track_length"):
        await call_tool_text(
            server,
            "tune_track_length",
            {"net_name": "NET1", "target_length_mm": 5.0},
        )


@pytest.mark.anyio
async def test_export_manufacturing_package_accepts_explicit_variant(
    sample_project: Path,
    monkeypatch,
) -> None:
    commands: list[list[str]] = []

    def fake_run_cli_variants(variants: list[list[str]]) -> tuple[int, str, str]:
        command = variants[0]
        commands.append(command)
        output_index = command.index("--output") + 1
        output_path = Path(command[output_index])
        if output_path.suffix:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text("generated\n", encoding="utf-8")
        else:
            output_path.mkdir(parents=True, exist_ok=True)
            (output_path / "board-F_Cu.gbr").write_text("gerber\n", encoding="utf-8")
        return 0, "", ""

    monkeypatch.setattr(
        "kicad_mcp.tools.validation._evaluate_project_gate",
        lambda **_kwargs: [],
    )
    monkeypatch.setattr("kicad_mcp.tools.export._run_cli_variants", fake_run_cli_variants)
    monkeypatch.setattr(
        "kicad_mcp.tools.export.get_cli_capabilities",
        lambda _cli: CliCapabilities(
            version="KiCad 10.0.1",
            gerber_command="gerber",
            drill_command="drill",
            position_command="pos",
            supports_ipc2581=True,
        ),
    )

    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})
    await call_tool_text(server, "variant_create", {"name": "lite"})

    result = await call_tool_text(server, "export_manufacturing_package", {"variant": "lite"})

    assert "Gerber export completed" in result
    assert commands
    assert all("--variant" in command and "lite" in command for command in commands)
    active = await call_tool_text(server, "variant_list", {})
    assert '"active_variant": "default"' in active


def test_structured_error_code_unavailable() -> None:
    from kicad_mcp.server import _structured_tool_error_from_message

    result = _structured_tool_error_from_message("kicad-cli is missing")
    assert result.isError is True
    assert result.structuredContent["error_code"] == "CLI_UNAVAILABLE"


def test_health_doctor_schema_and_secret_masking(
    sample_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ = sample_project
    reset_config()
    cfg = get_config()
    cfg.auth_token = "secret-token"  # noqa: S105
    cfg.kicad_token = "kicad-secret"  # noqa: S105

    from kicad_mcp.diagnostics import build_doctor_report, build_health_report

    health = build_health_report()
    assert health.ok is True
    config_diag = health.config
    assert config_diag.auth_token == {"configured": True}
    assert config_diag.kicad_token == {"configured": True}
    # Ensure secrets are NOT in the output
    health_json = health.model_dump_json()
    assert "secret-token" not in health_json
    assert "kicad-secret" not in health_json

    doctor = build_doctor_report()
    # doctor might not be 'ok' if KiCad is not running, but it should have stable keys
    assert hasattr(doctor, "status")
    assert hasattr(doctor, "checks")
    doctor_json = doctor.model_dump_json()
    assert "secret-token" not in doctor_json
    assert "kicad-secret" not in doctor_json


@pytest.mark.anyio
async def test_export_path_traversal_rejection_strengthened(
    sample_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "kicad_mcp.tools.export.get_cli_capabilities",
        lambda _cli: CliCapabilities(
            version="KiCad 10.0.1",
            supports_step=True,
        ),
    )
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    # Test various traversal attempts
    traversals = [
        "../outside.step",
        "../../outside.step",
        "/absolute/path/board.step",
        "nested/../../outside.step",
        " ",
        ".",
        "..",
    ]

    for path in traversals:
        result = await call_tool_text(server, "export_step", {"output_path": path})
        assert "Invalid output path" in result or "traversal" in result.lower()


def test_tool_registry_invariants_and_profiles() -> None:
    from kicad_mcp.tools.router import (
        TOOL_CATEGORIES,
        available_profiles,
        categories_for_profile,
    )

    # All tools in categories must exist in some way or be registered
    for _category, info in TOOL_CATEGORIES.items():
        assert "tools" in info
        assert isinstance(info["tools"], list)

    # Critical profiles must be stable
    for profile in ["full", "minimal", "pcb", "schematic", "agent_full"]:
        assert profile in available_profiles()
        categories = categories_for_profile(profile)
        assert len(categories) > 0


@pytest.mark.anyio
async def test_lazy_startup_idempotency_and_deferral() -> None:
    from kicad_mcp.server import build_server

    server = build_server("minimal", defer_registration=True)
    assert server._lazy_registration_complete is False

    # First call should trigger registration
    tools = await server.list_tools()
    assert server._lazy_registration_complete is True
    count = len(tools)

    # Repeated calls should be idempotent and not duplicate tools
    tools_repeated = await server.list_tools()
    assert server._lazy_registration_complete is True
    assert len(tools_repeated) == count
