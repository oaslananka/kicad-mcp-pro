"""Regression: every Freerouting run must turn off its phone-home and server features.

Freerouting 2.x sends usage analytics and telemetry by default and can start a
GUI, a REST API server and an MCP server. An autorouter run from the MCP
server is a headless batch job on a private board file, so none of that should
be on. Freerouting reads these settings from ``--<section>.<key>=<value>``
arguments, the same form the runner already uses for ``--router.max_passes``.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from kicad_mcp.utils.freerouting import FreeRoutingRunner

EXPECTED_PRIVACY_ARGS = (
    "--usage_and_diagnostic_data.disable_analytics=true",
    "--profile.allow_telemetry=false",
    "--gui.enabled=false",
    "--api_server.enabled=false",
    "--mcp_server.enabled=false",
)


@pytest.mark.parametrize("use_docker", [True, False], ids=["docker", "jar"])
def test_every_freerouting_command_disables_analytics_telemetry_gui_and_servers(
    sample_project: Path,
    monkeypatch: pytest.MonkeyPatch,
    use_docker: bool,
) -> None:
    dsn_path = sample_project / "board.dsn"
    ses_path = sample_project / "board.ses"
    jar_path = sample_project / "freerouting.jar"
    dsn_path.write_text("(pcb (net A))", encoding="utf-8")
    jar_path.write_text("jar", encoding="utf-8")
    observed: list[list[str]] = []

    def fake_run(cmd: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        observed.append(cmd)
        ses_path.write_text("ses", encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, stdout="100% routed", stderr="")

    monkeypatch.setattr("kicad_mcp.utils.freerouting.subprocess.run", fake_run)
    monkeypatch.setattr("kicad_mcp.utils.freerouting._docker_available", lambda _: use_docker)

    FreeRoutingRunner().run_freerouting(
        dsn_path,
        ses_path,
        use_docker=use_docker,
        freerouting_jar_path=None if use_docker else jar_path,
    )

    assert len(observed) == 1
    command = observed[0]
    assert command[0] == ("docker" if use_docker else "java")
    for argument in EXPECTED_PRIVACY_ARGS:
        assert argument in command, f"{argument} missing from {command}"
