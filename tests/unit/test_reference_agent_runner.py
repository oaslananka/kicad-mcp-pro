from __future__ import annotations

import json
from pathlib import Path

import pytest


def _stream_rows() -> list[dict[str, object]]:
    return [
        {
            "type": "system",
            "subtype": "init",
            "model": "claude-sonnet-5",
            "tools": ["ToolSearch", "mcp__kicad__kicad_get_server_info"],
            "plugins": [],
            "mcp_servers": [{"name": "kicad", "status": "connected"}],
        },
        {
            "type": "assistant",
            "timestamp": "2026-09-03T19:36:45.698Z",
            "message": {
                "role": "assistant",
                "model": "claude-sonnet-5",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "tool-1",
                        "name": "ToolSearch",
                        "input": {"query": "secret raw query"},
                    }
                ],
            },
        },
        {
            "type": "assistant",
            "timestamp": "2026-09-03T19:36:46.000Z",
            "message": {
                "role": "assistant",
                "model": "claude-sonnet-5",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "tool-2",
                        "name": "mcp__kicad__kicad_get_server_info",
                        "input": {"raw": "do-not-publish"},
                    }
                ],
            },
        },
        {
            "type": "user",
            "timestamp": "2026-09-03T19:36:47.000Z",
            "message": {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "tool-2",
                        "content": "raw tool output must not survive",
                    }
                ],
            },
        },
        {
            "type": "result",
            "subtype": "success",
            "is_error": False,
            "terminal_reason": "completed",
            "permission_denials": [],
            "modelUsage": {
                "claude-sonnet-5": {"canonicalModel": "claude-sonnet-5", "provider": "firstParty"},
                "claude-haiku-4-5-20251001": {
                    "canonicalModel": "claude-haiku-4-5-20251001",
                    "provider": "firstParty",
                },
            },
        },
    ]


def _lines(rows: list[dict[str, object]]) -> list[str]:
    return [json.dumps(row) for row in rows]


def test_parse_claude_stream_emits_only_sanitized_kicad_events() -> None:
    from kicad_mcp.evals.reference_agent_runner import parse_claude_stream

    summary = parse_claude_stream(_lines(_stream_rows()), attempt_id="attempt-001")

    assert summary.primary_model == "claude-sonnet-5"
    assert summary.auxiliary_models == ("claude-haiku-4-5-20251001",)
    assert summary.provider == "firstParty"
    assert summary.permission_denials == 0
    assert summary.successful is True
    assert [
        (event.sequence, event.event_type, event.name, event.status) for event in summary.events
    ] == [
        (1, "tool_call", "kicad_get_server_info", "started"),
        (2, "tool_result", "kicad_get_server_info", "completed"),
    ]
    rendered = "\n".join(event.model_dump_json() for event in summary.events)
    assert "secret raw query" not in rendered
    assert "do-not-publish" not in rendered
    assert "raw tool output" not in rendered


def test_parse_claude_stream_rejects_unreviewed_executed_tool() -> None:
    from kicad_mcp.evals.reference_agent_runner import (
        ReferenceAgentRunnerError,
        parse_claude_stream,
    )

    rows = _stream_rows()
    rows.insert(
        2,
        {
            "type": "assistant",
            "timestamp": "2026-09-03T19:36:45.900Z",
            "message": {
                "role": "assistant",
                "model": "claude-sonnet-5",
                "content": [{"type": "tool_use", "id": "bad", "name": "Bash", "input": {}}],
            },
        },
    )

    with pytest.raises(ReferenceAgentRunnerError, match="unreviewed tool"):
        parse_claude_stream(_lines(rows), attempt_id="attempt-001")


def test_parse_claude_stream_rejects_available_execution_tools() -> None:
    from kicad_mcp.evals.reference_agent_runner import (
        ReferenceAgentRunnerError,
        parse_claude_stream,
    )

    rows = _stream_rows()
    rows[0]["tools"] = ["ToolSearch", "Bash", "mcp__kicad__kicad_get_server_info"]

    with pytest.raises(ReferenceAgentRunnerError, match="tool inventory"):
        parse_claude_stream(_lines(rows), attempt_id="attempt-001")


def test_build_claude_command_exposes_only_reviewed_agent_surface(tmp_path) -> None:
    from kicad_mcp.evals.reference_agent_runner import build_claude_command

    command = build_claude_command(
        claude_executable="claude",
        model="claude-sonnet-5",
        settings_path=tmp_path / "settings.json",
        mcp_config_path=tmp_path / "mcp.json",
    )

    assert command == (
        "claude",
        "-p",
        "--model",
        "claude-sonnet-5",
        "--setting-sources",
        "project",
        "--settings",
        str(tmp_path / "settings.json"),
        "--strict-mcp-config",
        "--mcp-config",
        str(tmp_path / "mcp.json"),
        "--tools",
        "ToolSearch",
        "--allowedTools",
        "mcp__kicad__*",
        "--output-format",
        "stream-json",
        "--verbose",
    )
    assert not {"Bash", "Read", "Write", "Edit", "WebFetch"}.intersection(command)


def test_build_mcp_config_pins_phase_and_local_runtime(tmp_path) -> None:
    from kicad_mcp.evals.reference_agent_runner import ReferenceAgentPhase, build_mcp_config

    phase = ReferenceAgentPhase.for_name("pcb")
    config = build_mcp_config(
        phase=phase,
        uv_executable=tmp_path / "uv.exe",
        checkout_dir=tmp_path / "repo",
        project_dir=tmp_path / "project",
        kicad_cli=tmp_path / "kicad-cli.exe",
    )

    server = config["mcpServers"]["kicad"]
    assert server["command"] == str(tmp_path / "uv.exe")
    assert server["args"] == [
        "--directory",
        str(tmp_path / "repo"),
        "run",
        "--frozen",
        "kicad-mcp-pro",
    ]
    assert server["env"] == {
        "KICAD_MCP_PROJECT_DIR": str(tmp_path / "project"),
        "KICAD_MCP_PROFILE": "build",
        "KICAD_MCP_OPERATING_MODE": "write",
        "KICAD_MCP_KICAD_CLI": str(tmp_path / "kicad-cli.exe"),
    }


def test_reference_agent_phases_are_fixed() -> None:
    from kicad_mcp.evals.reference_agent_runner import ReferenceAgentPhase

    assert ReferenceAgentPhase.for_name("schematic").profile == "build"
    assert ReferenceAgentPhase.for_name("schematic").mode == "write"
    assert ReferenceAgentPhase.for_name("pcb").profile == "build"
    assert ReferenceAgentPhase.for_name("pcb").mode == "write"
    assert ReferenceAgentPhase.for_name("manufacturing").profile == "release"
    assert ReferenceAgentPhase.for_name("manufacturing").mode == "manufacturing"


def test_run_claude_session_uses_stdin_and_writes_only_stream_to_scratch(
    tmp_path, monkeypatch
) -> None:
    import subprocess

    from kicad_mcp.evals.reference_agent_runner import run_claude_session

    calls = []
    stdout = "\n".join(_lines(_stream_rows())) + "\n"

    def fake_run(command: tuple[str, ...], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="private stderr")

    monkeypatch.setattr(subprocess, "run", fake_run)
    raw_stream = tmp_path / "scratch" / "stream.jsonl"
    summary = run_claude_session(
        command=("claude", "-p"),
        prompt="public benchmark prompt",
        raw_stream_path=raw_stream,
        attempt_id="attempt-001",
        cwd=tmp_path,
        timeout_seconds=120.0,
    )

    assert summary.successful is True
    assert raw_stream.read_text(encoding="utf-8") == stdout
    command, kwargs = calls[0]
    assert "public benchmark prompt" not in command
    assert kwargs["input"] == "public benchmark prompt"
    assert kwargs["shell"] is False
    assert kwargs["timeout"] == 120.0
    assert kwargs["capture_output"] is True
    assert kwargs["text"] is True
    assert "private stderr" not in raw_stream.read_text(encoding="utf-8")


def test_write_agent_log_serializes_only_sanitized_events(tmp_path) -> None:
    from kicad_mcp.evals.reference_agent_runner import parse_claude_stream, write_agent_log

    summary = parse_claude_stream(_lines(_stream_rows()), attempt_id="attempt-001")
    target = tmp_path / "agent-log.jsonl"
    write_agent_log(target, summary)

    rendered = target.read_text(encoding="utf-8")
    assert rendered.count("\n") == 2
    assert "raw tool output" not in rendered
    assert "do-not-publish" not in rendered
    assert "kicad_get_server_info" in rendered


def test_write_agent_log_appends_with_contiguous_sequences(tmp_path) -> None:
    from kicad_mcp.evals.reference_agent_runner import parse_claude_stream, write_agent_log

    summary = parse_claude_stream(_lines(_stream_rows()), attempt_id="attempt-001")
    target = tmp_path / "agent-log.jsonl"
    write_agent_log(target, summary)
    write_agent_log(target, summary, append=True)

    payloads = [json.loads(line) for line in target.read_text(encoding="utf-8").splitlines()]
    assert [item["sequence"] for item in payloads] == [1, 2, 3, 4]
    assert all(item["attempt_id"] == "attempt-001" for item in payloads)


def test_reference_agent_cli_exposes_explicit_runtime_inputs() -> None:
    import subprocess
    import sys
    from pathlib import Path

    script = Path(__file__).resolve().parents[2] / "scripts/run_reference_board_agent.py"
    completed = subprocess.run(
        [sys.executable, str(script), "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0
    for flag in (
        "--attempt-id",
        "--phase",
        "--prompt-file",
        "--project-dir",
        "--scratch-dir",
        "--agent-log",
        "--checkout-dir",
        "--uv",
        "--kicad-cli",
        "--claude",
        "--model",
    ):
        assert flag in completed.stdout


def test_load_phase_prompt_combines_common_and_selected_phase(tmp_path) -> None:
    from kicad_mcp.evals.reference_agent_runner import ReferenceAgentPhase, load_phase_prompt

    source = tmp_path / "original-prompt.md"
    source.write_text(
        "# Benchmark\n\nCommon invariant.\n\n## Phase: schematic\nBuild schematic.\n\n"
        "## Phase: pcb\nBuild PCB.\n\n## Phase: manufacturing\nExport release.\n",
        encoding="utf-8",
    )
    prompt = load_phase_prompt(source, ReferenceAgentPhase.for_name("pcb"))
    assert "Common invariant." in prompt
    assert "Build PCB." in prompt
    assert "Build schematic." not in prompt
    assert "Export release." not in prompt


@pytest.mark.parametrize(
    "board_id",
    ("esp32-c6-usbc", "stm32f072-usbc", "rp2350-usbc"),
)
def test_reference_board_inputs_are_reviewed_clean_start_contracts(board_id: str) -> None:
    from kicad_mcp.evals.task_outcomes import ALL_TASK_STAGES, parse_benchmark_contract

    root = Path(__file__).resolve().parents[2] / "docs/evidence/reference-boards" / board_id / "v1"
    assert (root / "specification.md").is_file()
    assert (root / "original-prompt.md").is_file()
    contract = parse_benchmark_contract(
        json.loads((root / "benchmark.json").read_text(encoding="utf-8"))
    )
    assert contract.benchmark_version == "v1"
    assert contract.evidence_sufficiency.minimum_valid_attempts == 2
    assert contract.evidence_sufficiency.minimum_recovery_required_mutations == 2
    assert contract.evidence_sufficiency.minimum_drc_required_tasks == 2
    assert contract.evidence_sufficiency.minimum_manufacturing_release_tasks == 2
    assert len(contract.tasks) == 1
    assert contract.tasks[0].task_class == "reference-board"
    assert set(contract.tasks[0].stage_requirements) == set(ALL_TASK_STAGES)
    assert set(contract.tasks[0].stage_requirements.values()) == {"required"}
    assert not (root / "attempt-manifest.json").exists()
    assert not (root / "attempts").exists()
    assert not list(root.glob("*.kicad_sch"))
    assert not list(root.glob("*.kicad_pcb"))

    from kicad_mcp.evals.evidence_sanitization import validate_sanitized_evidence
    from kicad_mcp.evals.reference_agent_runner import ReferenceAgentPhase, load_phase_prompt

    validate_sanitized_evidence((root / "specification.md").read_text(encoding="utf-8"))
    validate_sanitized_evidence((root / "original-prompt.md").read_text(encoding="utf-8"))
    for phase_name in ("schematic", "pcb", "manufacturing"):
        phase_prompt = load_phase_prompt(
            root / "original-prompt.md", ReferenceAgentPhase.for_name(phase_name)
        )
        validate_sanitized_evidence(phase_prompt)


def test_parse_claude_stream_requires_only_connected_kicad_mcp() -> None:
    from kicad_mcp.evals.reference_agent_runner import (
        ReferenceAgentRunnerError,
        parse_claude_stream,
    )

    rows = _stream_rows()
    rows[0]["mcp_servers"] = [
        {"name": "kicad", "status": "connected"},
        {"name": "unreviewed", "status": "connected"},
    ]

    with pytest.raises(ReferenceAgentRunnerError, match="MCP server inventory"):
        parse_claude_stream(_lines(rows), attempt_id="attempt-001")


def test_run_claude_session_preserves_parseable_failed_session(tmp_path, monkeypatch) -> None:
    import subprocess

    from kicad_mcp.evals.reference_agent_runner import run_claude_session

    rows = _stream_rows()
    rows[1:4] = []
    rows[-1]["subtype"] = "error"
    rows[-1]["is_error"] = True
    rows[-1]["terminal_reason"] = "provider_failure"
    stdout = "\n".join(_lines(rows)) + "\n"

    def fake_run(command: tuple[str, ...], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 1, stdout=stdout, stderr="private")

    monkeypatch.setattr(subprocess, "run", fake_run)
    summary = run_claude_session(
        command=("claude", "-p"),
        prompt="benchmark",
        raw_stream_path=tmp_path / "stream.jsonl",
        attempt_id="attempt-002",
        cwd=tmp_path,
        timeout_seconds=30.0,
    )
    assert summary.successful is False
    assert [(event.event_type, event.name, event.status) for event in summary.events] == [
        ("workflow", "claude_session", "started"),
        ("workflow", "claude_session", "failed"),
    ]


def test_reviewed_mcp_tools_follow_profile_and_mode_boundaries() -> None:
    from kicad_mcp.evals.reference_agent_runner import ReferenceAgentPhase, reviewed_mcp_tools

    build = reviewed_mcp_tools(ReferenceAgentPhase.for_name("schematic"))
    release = reviewed_mcp_tools(ReferenceAgentPhase.for_name("manufacturing"))

    assert len(build) == 24
    assert "mcp__kicad__sch_apply_plan" in build
    assert "mcp__kicad__export_manufacturing_package" not in build
    assert len(release) == 24
    assert "mcp__kicad__export_manufacturing_package" in release
    assert "mcp__kicad__sch_apply_plan" not in release


def test_parse_claude_stream_rejects_tool_outside_reviewed_phase_surface() -> None:
    from kicad_mcp.evals.reference_agent_runner import (
        ReferenceAgentRunnerError,
        parse_claude_stream,
    )

    allowed = frozenset({"mcp__kicad__kicad_set_project"})
    with pytest.raises(ReferenceAgentRunnerError, match="reviewed phase surface"):
        parse_claude_stream(
            _lines(_stream_rows()),
            attempt_id="attempt-001",
            allowed_mcp_tools=allowed,
        )
