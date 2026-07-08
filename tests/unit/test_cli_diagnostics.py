from __future__ import annotations

import inspect
import json
import zipfile
from pathlib import Path

from typer.testing import CliRunner

from kicad_mcp.config import reset_config
from kicad_mcp.connection import KiCadConnectionError
from kicad_mcp.diagnostics import (
    CheckResult,
    ConfigDiagnostics,
    DiagnosticReport,
    KiCadDiagnostics,
    McpDiagnostics,
    build_diagnostic_report,
)
from kicad_mcp.server import app


def _diagnostic_report(checks: list[CheckResult]) -> DiagnosticReport:
    return DiagnosticReport(
        ok=not any(check.status == "error" for check in checks),
        status="error"
        if any(check.status == "error" for check in checks)
        else "degraded"
        if any(check.status == "warn" for check in checks)
        else "ok",
        mcp=McpDiagnostics(transport_default="stdio", profile="agent_full"),
        kicad=KiCadDiagnostics(cli_path=None, cli_found=False),
        config=ConfigDiagnostics(
            workspace_root=None,
            project_dir=None,
            output_dir=None,
            timeout_ms=5000,
            retries=2,
            headless=True,
            log_level="INFO",
            log_format="console",
            transport="stdio",
            auth_token={"configured": False},
            kicad_token={"configured": False},
        ),
        checks=checks,
    )


def test_cli_health_json_does_not_require_kicad(sample_project: Path) -> None:
    _ = sample_project
    result = CliRunner().invoke(app, ["health", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["package"]["name"] == "kicad-mcp-pro"
    assert payload["kicad"]["ipc_reachable"] is False
    assert payload["checks"][-1]["name"] == "kicad_ipc"
    assert payload["checks"][-1]["status"] == "skipped"


def test_cli_doctor_json_reports_unavailable_kicad_without_stack_trace(
    sample_project: Path,
    monkeypatch,
) -> None:
    _ = sample_project
    monkeypatch.setattr("kicad_mcp.diagnostics.find_kicad_version", lambda _path: "KiCad 10.0.1")
    monkeypatch.setattr(
        "kicad_mcp.diagnostics.get_board",
        lambda: (_ for _ in ()).throw(KiCadConnectionError("IPC not reachable")),
    )

    result = CliRunner().invoke(app, ["doctor", "--json"])

    assert result.exit_code == 0, result.output
    assert "Traceback" not in result.output
    payload = json.loads(result.output)
    assert payload["status"] == "degraded"
    assert payload["kicad"]["version"] == "KiCad 10.0.1"
    assert any(check["name"] == "kicad_ipc" for check in payload["checks"])


def test_cli_doctor_json_includes_schema_validated_setup_diagnostics(
    sample_project: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("KICAD_MCP_TRANSPORT", "http")
    monkeypatch.setenv("KICAD_MCP_HOST", "127.0.0.1")
    monkeypatch.setenv("KICAD_MCP_PORT", "4173")
    monkeypatch.setenv("KICAD_MCP_MOUNT_PATH", "/custom-mcp")
    monkeypatch.setenv("KICAD_MCP_STATEFUL_HTTP", "true")
    monkeypatch.setattr("kicad_mcp.diagnostics.find_kicad_version", lambda _path: "KiCad 10.0.4")
    monkeypatch.setattr(
        "kicad_mcp.diagnostics.get_board",
        lambda: (_ for _ in ()).throw(KiCadConnectionError("IPC not reachable token=super-secret")),
    )
    reset_config()

    result = CliRunner().invoke(app, ["doctor", "--json"])

    assert result.exit_code == 0, result.output
    assert "super-secret" not in result.output
    payload = json.loads(result.output)
    DiagnosticReport.model_validate(payload)
    schema = DiagnosticReport.model_json_schema(by_alias=True)
    assert "schemaVersion" in schema["properties"]
    assert payload["schemaVersion"] == "1.0.0"
    assert payload["mcp"]["transport_default"] == "streamable-http"
    assert payload["mcp"]["host"] == "127.0.0.1"
    assert payload["mcp"]["port"] == 4173
    assert payload["mcp"]["mount_path"] == "/custom-mcp"
    assert payload["mcp"]["stateful_http"] is True
    assert payload["config"]["project_file"].endswith("demo.kicad_pro")
    assert payload["config"]["pcb_file"].endswith("demo.kicad_pcb")
    assert payload["config"]["sch_file"].endswith("demo.kicad_sch")
    assert payload["tools"]["tool_count"] > 0
    assert payload["tools"]["category_count"] > 0
    assert payload["tools"]["capability_summary"]["tiers"]["read"] > 0
    assert payload["live_context"]["available"] is False
    assert payload["recent_errors"]
    assert "super-secret" not in json.dumps(payload["recent_errors"])


def test_doctor_reports_checkout_version_drift(
    tmp_path: Path,
    monkeypatch,
) -> None:
    checkout = tmp_path / "kicad-mcp"
    checkout.mkdir()
    (checkout / "pyproject.toml").write_text(
        '[project]\nname = "kicad-mcp-pro"\nversion = "99.0.0"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("KICAD_MCP_REPO_PATH", str(checkout))
    monkeypatch.setattr("kicad_mcp.diagnostics._agent_config_checks", lambda: [])

    report = build_diagnostic_report(probe_cli=True, probe_ipc=False)

    assert report.status == "degraded"
    assert report.package.location
    assert report.package.repo_path == str(checkout.resolve())
    assert report.package.repo_version == "99.0.0"
    assert report.package.version_drift is True
    drift = [check for check in report.checks if check.name == "package_version_drift"]
    assert len(drift) == 1
    assert drift[0].status == "warn"
    assert "Active server version" in drift[0].message
    assert "Restart the MCP server" in drift[0].hint


def test_doctor_reports_checkout_uv_required_version_mismatch(
    tmp_path: Path,
    monkeypatch,
) -> None:
    checkout = tmp_path / "kicad-mcp"
    checkout.mkdir()
    (checkout / "pyproject.toml").write_text(
        '[project]\nname = "kicad-mcp-pro"\nversion = "3.12.1"\n',
        encoding="utf-8",
    )
    (checkout / "uv.toml").write_text('required-version = "0.10.8"\n', encoding="utf-8")
    monkeypatch.setenv("KICAD_MCP_REPO_PATH", str(checkout))
    monkeypatch.setattr("kicad_mcp.diagnostics._agent_config_checks", lambda: [])
    monkeypatch.setattr(
        "kicad_mcp.diagnostics._detect_uv_version",
        lambda: ("0.11.19", "C:/tools/uv.exe"),
    )

    report = build_diagnostic_report(probe_cli=True, probe_ipc=False)

    checks = [check for check in report.checks if check.name == "uv_version"]
    assert len(checks) == 1
    assert checks[0].status == "warn"
    assert "Checkout requires uv 0.10.8" in checks[0].message
    assert "uv run will fail before tests or tools start" in checks[0].message
    assert "uv self update 0.10.8" in checks[0].hint


def test_cli_doctor_bundle_writes_redacted_debug_zip(
    sample_project: Path,
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("KICAD_MCP_AUTH_TOKEN", "bundle-secret-token")
    monkeypatch.setenv("KICAD_API_TOKEN", "bundle-kicad-token")
    monkeypatch.setattr("kicad_mcp.diagnostics.find_kicad_version", lambda _path: "KiCad 10.0.4")
    monkeypatch.setattr(
        "kicad_mcp.diagnostics.get_board",
        lambda: (_ for _ in ()).throw(KiCadConnectionError("IPC unavailable")),
    )
    reset_config()
    bundle_path = tmp_path / "mcp-debug.zip"

    result = CliRunner().invoke(app, ["doctor", "--json", "--bundle", str(bundle_path)])

    assert result.exit_code == 0, result.output
    assert bundle_path.exists()
    with zipfile.ZipFile(bundle_path) as bundle:
        assert set(bundle.namelist()) == {
            "diagnostic-schema.json",
            "doctor.json",
            "environment.json",
            "README.txt",
        }
        doctor_payload = json.loads(bundle.read("doctor.json"))
        DiagnosticReport.model_validate(doctor_payload)
        combined = "\n".join(
            bundle.read(name).decode("utf-8", errors="replace") for name in bundle.namelist()
        )
    assert doctor_payload["schemaVersion"] == "1.0.0"
    assert "bundle-secret-token" not in combined
    assert "bundle-kicad-token" not in combined
    assert "configured" in combined


def test_cli_version_and_serve_help(sample_project: Path) -> None:
    _ = sample_project
    runner = CliRunner()

    version = runner.invoke(app, ["version", "--json"])
    serve_help = runner.invoke(app, ["serve", "--help"])

    assert version.exit_code == 0, version.output
    assert json.loads(version.output)["package"]["version"]
    assert serve_help.exit_code == 0, serve_help.output
    assert "Start the MCP server explicitly" in serve_help.output


def test_cli_dashboard_help_exposes_mode_option(sample_project: Path) -> None:
    """The dashboard subcommand runs --help cleanly (sanity check for the added option)."""
    _ = sample_project
    runner = CliRunner()

    dashboard_help = runner.invoke(app, ["dashboard", "--help"])

    assert dashboard_help.exit_code == 0, dashboard_help.output


def test_cli_dashboard_accepts_mode_option() -> None:
    """The dashboard subcommand declares --mode, matching serve's operating-mode option.

    Inspects the Typer callback's parameter declarations directly rather than
    parsing --help text, since Rich-rendered help output wraps differently
    depending on the terminal width detected in CI vs. local dev shells.
    """
    dashboard_info = next(c for c in app.registered_commands if c.callback.__name__ == "dashboard")
    sig = inspect.signature(dashboard_info.callback)
    operating_mode_param = sig.parameters["operating_mode"]
    assert operating_mode_param.default.param_decls == ("--mode",)


def test_cli_tools_list_json(sample_project: Path) -> None:
    _ = sample_project

    result = CliRunner().invoke(app, ["tools", "list", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    names = {tool["name"] for tool in payload}
    assert "kicad_get_project_info" in names
    assert "kicad_list_tool_categories" in names
    assert all("inputSchema" in tool for tool in payload)


def test_cli_capabilities_json(sample_project: Path) -> None:
    _ = sample_project

    result = CliRunner().invoke(app, ["capabilities", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    by_name = {record["name"]: record for record in payload}
    assert by_name["export_manufacturing_package"]["human_gate_required"] is True
    assert by_name["kicad_health"]["verification_level"] == "verified"


def test_cli_mcp_config_generator_outputs_supported_clients(sample_project: Path) -> None:
    _ = sample_project
    runner = CliRunner()

    claude = runner.invoke(app, ["mcp-config", "generate", "--client", "claude"])
    codex = runner.invoke(app, ["mcp-config", "generate", "--client", "codex"])

    assert claude.exit_code == 0, claude.output
    assert json.loads(claude.output)["mcpServers"]["kicad-mcp-pro"]["command"] == "uvx"
    assert codex.exit_code == 0, codex.output
    assert "[mcp_servers.kicad-mcp-pro]" in codex.output
    assert 'args = ["kicad-mcp-pro"]' in codex.output


def test_cli_doctor_strict_exit_codes(monkeypatch) -> None:
    runner = CliRunner()

    monkeypatch.setattr(
        "kicad_mcp.server.build_doctor_report",
        lambda: _diagnostic_report(
            [CheckResult(name="kicad_ipc", status="warn", message="IPC not reachable")]
        ),
    )
    degraded = runner.invoke(app, ["doctor", "--json", "--strict"])
    assert degraded.exit_code == 1, degraded.output

    monkeypatch.setattr(
        "kicad_mcp.server.build_doctor_report",
        lambda: _diagnostic_report(
            [CheckResult(name="kicad_cli", status="warn", message="kicad-cli missing")]
        ),
    )
    missing_external = runner.invoke(app, ["doctor", "--json", "--strict"])
    assert missing_external.exit_code == 3, missing_external.output
