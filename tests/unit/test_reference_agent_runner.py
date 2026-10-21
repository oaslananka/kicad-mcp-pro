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
                    {"type": "text", "text": "Thinking about the query"},
                    {
                        "type": "tool_use",
                        "id": "tool-1",
                        "name": "ToolSearch",
                        "input": {"query": "secret raw query"},
                    },
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


def _workspace(tmp_path: Path, prompt_text: str | None = None, *, attempt_id: str = "attempt-001"):
    from kicad_mcp.evals.reference_agent_runner import ReferenceAgentWorkspace

    board = tmp_path / "docs/evidence/reference-boards/test-board/v1"
    board.mkdir(parents=True, exist_ok=True)
    prompt = prompt_text or (
        "# Benchmark\nCommon.\n\n## Phase: schematic\nBuild.\n\n"
        "## Phase: pcb\nLayout.\n\n## Phase: manufacturing\nExport.\n"
    )
    (board / "original-prompt.md").write_text(prompt, encoding="utf-8")
    return ReferenceAgentWorkspace.for_board(
        checkout_dir=tmp_path, board_id="test-board", version="v1", attempt_id=attempt_id
    )


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

    stream_lines = _lines(rows)
    with pytest.raises(ReferenceAgentRunnerError, match="unreviewed tool"):
        parse_claude_stream(stream_lines, attempt_id="attempt-001")


def test_parse_claude_stream_rejects_available_execution_tools() -> None:
    from kicad_mcp.evals.reference_agent_runner import (
        ReferenceAgentRunnerError,
        parse_claude_stream,
    )

    rows = _stream_rows()
    rows[0]["tools"] = ["ToolSearch", "Bash", "mcp__kicad__kicad_get_server_info"]
    stream_lines = _lines(rows)

    with pytest.raises(ReferenceAgentRunnerError, match="tool inventory"):
        parse_claude_stream(stream_lines, attempt_id="attempt-001")


def test_build_claude_command_exposes_only_reviewed_agent_surface(tmp_path) -> None:
    from kicad_mcp.evals.reference_agent_runner import build_claude_command

    command = build_claude_command(
        settings_path=tmp_path / "settings.json",
        mcp_config_path=tmp_path / "mcp.json",
        allowed_mcp_tools=frozenset({"mcp__kicad__sch_add_symbol", "mcp__kicad__run_erc"}),
    )

    assert command[:4] == ("claude", "-p", "--model", "claude-sonnet-5")
    assert "--strict-mcp-config" in command
    assert "--tools" in command
    assert "ToolSearch" in command
    assert "--allowedTools" in command
    assert "mcp__kicad__run_erc,mcp__kicad__sch_add_symbol" in command
    for forbidden in ("Bash", "Read", "Write", "Edit", "WebFetch"):
        assert forbidden not in command


def test_build_mcp_config_pins_phase_and_current_python(tmp_path) -> None:
    import sys

    from kicad_mcp.evals.reference_agent_runner import ReferenceAgentPhase, build_mcp_config

    workspace = _workspace(tmp_path)
    phase = ReferenceAgentPhase.for_name("pcb")
    config = build_mcp_config(
        phase=phase, workspace=workspace, kicad_cli=tmp_path / "kicad-cli.exe"
    )
    server = config["mcpServers"]["kicad"]
    assert server["command"] == sys.executable
    assert server["args"] == ["-m", "kicad_mcp.server"]
    assert server["env"] == {
        "PYTHONPATH": str(workspace.checkout_dir / "src"),
        "KICAD_MCP_TRANSPORT": "stdio",
        "KICAD_MCP_PROTOCOL_LANE": "stable",
        "KICAD_MCP_PROJECT_DIR": str(workspace.project_dir),
        "KICAD_MCP_PROFILE": "pcb_layout",
        "KICAD_MCP_OPERATING_MODE": "write",
        "KICAD_MCP_KICAD_CLI": str(tmp_path / "kicad-cli.exe"),
    }


def test_reference_agent_phases_are_fixed() -> None:
    from kicad_mcp.evals.reference_agent_runner import ReferenceAgentPhase

    assert ReferenceAgentPhase.for_name("schematic").profile == "schematic_authoring"
    assert ReferenceAgentPhase.for_name("schematic").mode == "write"
    assert ReferenceAgentPhase.for_name("pcb").profile == "pcb_layout"
    assert ReferenceAgentPhase.for_name("pcb").mode == "write"
    assert ReferenceAgentPhase.for_name("manufacturing").profile == "release"
    assert ReferenceAgentPhase.for_name("manufacturing").mode == "manufacturing"


def test_run_claude_session_uses_stdin_and_writes_only_stream_to_scratch(
    tmp_path, monkeypatch
) -> None:
    import subprocess

    from kicad_mcp.evals.reference_agent_runner import ReferenceAgentPhase, run_claude_session

    calls = []
    stdout = "\n".join(_lines(_stream_rows())) + "\n"

    def fake_run(command: tuple[str, ...], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="private stderr")

    monkeypatch.setattr(subprocess, "run", fake_run)
    workspace = _workspace(tmp_path)
    phase = ReferenceAgentPhase.for_name("schematic")
    summary = run_claude_session(
        workspace=workspace, phase=phase, prompt="public benchmark prompt", timeout_seconds=120.0
    )
    raw_stream = workspace.phase_raw_stream_path(phase)
    assert summary.successful is True
    assert raw_stream.read_text(encoding="utf-8") == stdout
    command, kwargs = calls[0]
    assert command[:4] == ("claude", "-p", "--model", "claude-sonnet-5")
    assert "public benchmark prompt" not in command
    assert kwargs["input"] == "public benchmark prompt"
    assert kwargs["cwd"] == workspace.checkout_dir
    assert kwargs["shell"] is False
    assert kwargs["timeout"] == 120.0
    assert "private stderr" not in raw_stream.read_text(encoding="utf-8")


def test_write_agent_log_serializes_only_sanitized_events(tmp_path) -> None:
    from kicad_mcp.evals.reference_agent_runner import parse_claude_stream, write_agent_log

    summary = parse_claude_stream(_lines(_stream_rows()), attempt_id="attempt-001")
    workspace = _workspace(tmp_path)
    write_agent_log(workspace, summary)
    rendered = workspace.agent_log_path.read_text(encoding="utf-8")
    assert rendered.count("\n") == 2
    assert b"\r\n" not in workspace.agent_log_path.read_bytes()
    assert "raw tool output" not in rendered
    assert "do-not-publish" not in rendered
    assert "kicad_get_server_info" in rendered


def test_write_agent_log_appends_with_contiguous_sequences(tmp_path) -> None:
    from kicad_mcp.evals.reference_agent_runner import parse_claude_stream, write_agent_log

    summary = parse_claude_stream(_lines(_stream_rows()), attempt_id="attempt-001")
    workspace = _workspace(tmp_path)
    write_agent_log(workspace, summary)
    write_agent_log(workspace, summary, append=True)
    payloads = [
        json.loads(line)
        for line in workspace.agent_log_path.read_text(encoding="utf-8").splitlines()
    ]
    assert [item["sequence"] for item in payloads] == [1, 2, 3, 4]
    for item in payloads:
        assert item["attempt_id"] == "attempt-001"


def test_reference_agent_cli_exposes_only_reviewed_identity_inputs() -> None:
    import subprocess
    import sys

    script = Path(__file__).resolve().parents[2] / "scripts/run_reference_board_agent.py"
    completed = subprocess.run(
        [sys.executable, str(script), "--help"], capture_output=True, text=True, check=False
    )
    assert completed.returncode == 0
    for flag in ("--board-id", "--attempt-number", "--phase"):
        assert flag in completed.stdout
    for removed in (
        "--version",
        "--attempt-id",
        "--uv",
        "--kicad-cli",
        "--prompt-file",
        "--project-dir",
        "--scratch-dir",
        "--agent-log",
        "--checkout-dir",
        "--claude",
        "--model",
    ):
        assert removed not in completed.stdout


def test_load_phase_prompt_combines_common_and_selected_phase(tmp_path) -> None:
    from kicad_mcp.evals.reference_agent_runner import ReferenceAgentPhase, load_phase_prompt

    workspace = _workspace(
        tmp_path,
        "# Benchmark\n\nCommon invariant.\n\n## Phase: schematic\nBuild schematic.\n\n"
        "## Phase: pcb\nBuild PCB.\n\n## Phase: manufacturing\nExport release.\n",
    )
    prompt = load_phase_prompt(workspace, ReferenceAgentPhase.for_name("pcb"))
    assert "Common invariant." in prompt
    assert "Build PCB." in prompt
    assert "Build schematic." not in prompt
    assert "Export release." not in prompt


@pytest.mark.parametrize(
    "board_id",
    ("esp32-c6-usbc", "stm32f072-usbc", "rp2350-usbc"),
)
def test_reference_board_inputs_are_reviewed_clean_start_contracts(board_id: str) -> None:
    from kicad_mcp.evals.evidence_sanitization import validate_sanitized_evidence
    from kicad_mcp.evals.reference_agent_runner import (
        ReferenceAgentPhase,
        ReferenceAgentWorkspace,
        load_phase_prompt,
    )
    from kicad_mcp.evals.task_outcomes import ALL_TASK_STAGES, parse_benchmark_contract

    checkout = Path(__file__).resolve().parents[2]
    root = checkout / "docs/evidence/reference-boards" / board_id / "v1"
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
    manifest_path = root / "attempt-manifest.json"
    attempts_dir = root / "attempts"
    if manifest_path.exists():
        from kicad_mcp.evals.reference_corpus import validate_reference_board_bundle

        assert attempts_dir.is_dir()
        validate_reference_board_bundle(root)
    else:
        assert not attempts_dir.exists()
    assert not list(root.glob("*.kicad_sch"))
    assert not list(root.glob("*.kicad_pcb"))
    validate_sanitized_evidence((root / "specification.md").read_text(encoding="utf-8"))
    validate_sanitized_evidence((root / "original-prompt.md").read_text(encoding="utf-8"))
    workspace = ReferenceAgentWorkspace.for_board(
        checkout_dir=checkout, board_id=board_id, version="v1", attempt_id="attempt-001"
    )
    for phase_name in ("schematic", "pcb", "manufacturing"):
        validate_sanitized_evidence(
            load_phase_prompt(workspace, ReferenceAgentPhase.for_name(phase_name))
        )


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
    stream_lines = _lines(rows)

    with pytest.raises(ReferenceAgentRunnerError, match="MCP server inventory"):
        parse_claude_stream(stream_lines, attempt_id="attempt-001")


def test_run_claude_session_preserves_parseable_failed_session(tmp_path, monkeypatch) -> None:
    import subprocess

    from kicad_mcp.evals.reference_agent_runner import ReferenceAgentPhase, run_claude_session

    rows = _stream_rows()
    rows[1:4] = []
    rows[-1]["subtype"] = "error"
    rows[-1]["is_error"] = True
    rows[-1]["terminal_reason"] = "provider_failure"
    stdout = "\n".join(_lines(rows)) + "\n"

    def fake_run(command: tuple[str, ...], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 1, stdout=stdout, stderr="private")

    monkeypatch.setattr(subprocess, "run", fake_run)
    workspace = _workspace(tmp_path, attempt_id="attempt-002")
    summary = run_claude_session(
        workspace=workspace,
        phase=ReferenceAgentPhase.for_name("schematic"),
        prompt="benchmark",
        timeout_seconds=30.0,
    )
    assert summary.successful is False
    assert [(event.event_type, event.name, event.status) for event in summary.events] == [
        ("workflow", "claude_session", "started"),
        ("workflow", "claude_session", "failed"),
    ]


def test_reviewed_mcp_tools_follow_profile_and_mode_boundaries() -> None:
    from kicad_mcp.evals.reference_agent_runner import ReferenceAgentPhase, reviewed_mcp_tools

    schematic = reviewed_mcp_tools(ReferenceAgentPhase.for_name("schematic"))
    pcb = reviewed_mcp_tools(ReferenceAgentPhase.for_name("pcb"))
    release = reviewed_mcp_tools(ReferenceAgentPhase.for_name("manufacturing"))

    assert len(schematic) == 37
    assert {
        "mcp__kicad__sch_add_symbol",
        "mcp__kicad__lib_search_symbols",
        "mcp__kicad__run_erc",
    } <= schematic
    assert "mcp__kicad__pcb_route_trace" not in schematic
    assert len(pcb) == 38
    assert {
        "mcp__kicad__pcb_sync_from_schematic",
        "mcp__kicad__pcb_route_trace",
        "mcp__kicad__run_drc",
    } <= pcb
    assert "mcp__kicad__route_differential_pair" not in pcb
    assert len(release) >= 18
    assert "mcp__kicad__reference_generate_manufacturing_snapshot" in release
    assert "mcp__kicad__reference_compare_manufacturing_snapshots" in release
    assert "mcp__kicad__export_manufacturing_package" not in release


def test_parse_claude_stream_rejects_tool_outside_reviewed_phase_surface() -> None:
    from kicad_mcp.evals.reference_agent_runner import (
        ReferenceAgentRunnerError,
        parse_claude_stream,
    )

    allowed = frozenset({"mcp__kicad__kicad_set_project"})
    stream_lines = _lines(_stream_rows())
    with pytest.raises(ReferenceAgentRunnerError, match="reviewed phase surface"):
        parse_claude_stream(
            stream_lines,
            attempt_id="attempt-001",
            allowed_mcp_tools=allowed,
        )


def test_run_claude_session_preserves_invalid_stream_as_sanitized_failure(
    tmp_path, monkeypatch
) -> None:
    import subprocess

    from kicad_mcp.evals.reference_agent_runner import ReferenceAgentPhase, run_claude_session

    def fake_run(command: tuple[str, ...], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            command, 0, stdout="private invalid stream\n", stderr="private"
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    workspace = _workspace(tmp_path, attempt_id="attempt-003")
    phase = ReferenceAgentPhase.for_name("schematic")
    summary = run_claude_session(
        workspace=workspace, phase=phase, prompt="benchmark", timeout_seconds=30.0
    )
    raw = workspace.phase_raw_stream_path(phase)
    assert summary.successful is False
    assert summary.primary_model == "claude-sonnet-5"
    assert summary.terminal_reason == "stream_contract_violation"
    assert raw.read_text(encoding="utf-8") == "private invalid stream\n"
    assert [event.status for event in summary.events] == ["started", "failed"]
    rendered = json.dumps([event.model_dump(mode="json") for event in summary.events])
    assert "private" not in rendered


def test_run_claude_session_preserves_timeout_as_sanitized_failure(tmp_path, monkeypatch) -> None:
    import subprocess

    from kicad_mcp.evals.reference_agent_runner import ReferenceAgentPhase, run_claude_session

    def fake_run(command: tuple[str, ...], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(command, 30.0, output="private partial stream")

    monkeypatch.setattr(subprocess, "run", fake_run)
    workspace = _workspace(tmp_path, attempt_id="attempt-004")
    summary = run_claude_session(
        workspace=workspace,
        phase=ReferenceAgentPhase.for_name("schematic"),
        prompt="benchmark",
        timeout_seconds=30.0,
    )
    assert summary.successful is False
    assert summary.terminal_reason == "timeout"
    assert [event.status for event in summary.events] == ["started", "failed"]
    rendered = json.dumps([event.model_dump(mode="json") for event in summary.events])
    assert "private" not in rendered


def test_run_claude_session_preserves_launch_failure_without_exception_text(
    tmp_path, monkeypatch
) -> None:
    import subprocess

    from kicad_mcp.evals.reference_agent_runner import ReferenceAgentPhase, run_claude_session

    def fake_run(command: tuple[str, ...], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        raise OSError("private launch path")

    monkeypatch.setattr(subprocess, "run", fake_run)
    workspace = _workspace(tmp_path, attempt_id="attempt-005")
    summary = run_claude_session(
        workspace=workspace,
        phase=ReferenceAgentPhase.for_name("schematic"),
        prompt="benchmark",
        timeout_seconds=30.0,
    )
    assert summary.successful is False
    assert summary.terminal_reason == "process_launch_failed"
    assert [event.status for event in summary.events] == ["started", "failed"]
    rendered = json.dumps([event.model_dump(mode="json") for event in summary.events])
    assert "private" not in rendered


def test_catalog_boundary_is_broader_than_execution_boundary_for_authoring_phases() -> None:
    from kicad_mcp.evals.reference_agent_runner import (
        ReferenceAgentPhase,
        catalog_mcp_tools,
        reviewed_mcp_tools,
    )

    for phase_name in ("schematic", "pcb"):
        phase = ReferenceAgentPhase.for_name(phase_name)
        catalog = catalog_mcp_tools(phase)
        execution = reviewed_mcp_tools(phase)
        assert execution < catalog
        assert execution


def test_parse_claude_stream_allows_catalog_tool_but_rejects_unreviewed_execution() -> None:
    from kicad_mcp.evals.reference_agent_runner import (
        ReferenceAgentRunnerError,
        parse_claude_stream,
    )

    catalog = frozenset({"mcp__kicad__kicad_get_server_info", "mcp__kicad__kicad_set_project"})
    allowed = frozenset({"mcp__kicad__kicad_set_project"})
    stream_lines = _lines(_stream_rows())
    with pytest.raises(ReferenceAgentRunnerError, match="reviewed phase execution surface"):
        parse_claude_stream(
            stream_lines,
            attempt_id="attempt-001",
            catalog_mcp_tools=catalog,
            allowed_mcp_tools=allowed,
        )


def test_reference_agent_cli_threads_catalog_and_execution_boundaries(
    tmp_path, monkeypatch
) -> None:
    import importlib.util

    from kicad_mcp.evals.reference_agent_runner import ReferenceAgentRunSummary

    script = Path(__file__).resolve().parents[2] / "scripts/run_reference_board_agent.py"
    spec = importlib.util.spec_from_file_location("reference_agent_cli_test", script)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    board = tmp_path / "docs/evidence/reference-boards/esp32-c6-usbc/v1"
    board.mkdir(parents=True)
    (board / "original-prompt.md").write_text(
        "# Benchmark\nCommon.\n\n## Phase: schematic\nBuild.\n\n"
        "## Phase: pcb\nLayout.\n\n## Phase: manufacturing\nExport.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "discover_reference_kicad_cli", lambda: tmp_path / "kicad-cli.exe")
    captured: dict[str, object] = {}

    def fake_run(**kwargs: object) -> ReferenceAgentRunSummary:
        captured.update(kwargs)
        return ReferenceAgentRunSummary(
            events=(),
            primary_model="claude-sonnet-5",
            auxiliary_models=(),
            provider="firstParty",
            permission_denials=0,
            terminal_reason="completed",
            successful=True,
        )

    monkeypatch.setattr(module, "run_claude_session", fake_run)
    result = module.main(
        [
            "--board-id",
            "esp32-c6-usbc",
            "--attempt-number",
            "1",
            "--phase",
            "pcb",
        ]
    )
    assert result == 0
    execution = captured["allowed_mcp_tools"]
    catalog = captured["catalog_mcp_tools"]
    assert isinstance(execution, frozenset)
    assert isinstance(catalog, frozenset)
    assert execution < catalog
    assert "mcp__kicad__pcb_route_trace" in execution
    assert "mcp__kicad__route_differential_pair" not in execution
    workspace = captured["workspace"]
    assert workspace.checkout_dir == tmp_path.resolve()
    assert workspace.agent_log_path == board / "attempts/attempt-001/agent-log.jsonl"


def test_build_mcp_config_uses_benchmark_only_manufacturing_server(tmp_path) -> None:
    from kicad_mcp.evals.reference_agent_runner import ReferenceAgentPhase, build_mcp_config

    workspace = _workspace(tmp_path, attempt_id="attempt-003")
    config = build_mcp_config(
        phase=ReferenceAgentPhase.for_name("manufacturing"),
        workspace=workspace,
        kicad_cli=tmp_path / "kicad-cli",
    )
    server = config["mcpServers"]["kicad"]
    assert server["args"] == ["-m", "kicad_mcp.evals.reference_mcp_server"]
    assert server["env"]["KICAD_MCP_OPERATING_MODE"] == "manufacturing"


def test_reference_agent_cli_manufacturing_does_not_require_release_approval(
    tmp_path, monkeypatch
) -> None:
    import importlib.util

    from kicad_mcp.evals.reference_agent_runner import ReferenceAgentRunSummary

    script = Path(__file__).resolve().parents[2] / "scripts/run_reference_board_agent.py"
    spec = importlib.util.spec_from_file_location("reference_agent_benchmark_manufacturing", script)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    board = tmp_path / "docs/evidence/reference-boards/stm32f072-usbc/v1"
    board.mkdir(parents=True)
    (board / "original-prompt.md").write_text(
        "# Benchmark\nCommon.\n\n## Phase: schematic\nBuild.\n\n"
        "## Phase: pcb\nLayout.\n\n## Phase: manufacturing\nExport twice.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "discover_reference_kicad_cli", lambda: tmp_path / "kicad-cli")
    captured: dict[str, object] = {}

    def fake_run(**kwargs: object) -> ReferenceAgentRunSummary:
        captured.update(kwargs)
        return ReferenceAgentRunSummary(
            events=(),
            primary_model="claude-sonnet-5",
            auxiliary_models=(),
            provider="firstParty",
            permission_denials=0,
            terminal_reason="completed",
            successful=True,
        )

    monkeypatch.setattr(module, "run_claude_session", fake_run)
    assert (
        module.main(
            ["--board-id", "stm32f072-usbc", "--attempt-number", "3", "--phase", "manufacturing"]
        )
        == 0
    )
    assert "Reviewed manufacturing approval" not in captured["prompt"]
    assert "mcp__kicad__reference_generate_manufacturing_snapshot" in captured["allowed_mcp_tools"]
    assert "mcp__kicad__export_manufacturing_package" not in captured["allowed_mcp_tools"]


def test_reference_agent_workspace_derives_reviewed_paths(tmp_path) -> None:
    workspace = _workspace(tmp_path)
    board = tmp_path / "docs/evidence/reference-boards/test-board/v1"
    assert workspace.prompt_path == board / "original-prompt.md"
    assert workspace.agent_log_path == board / "attempts/attempt-001/agent-log.jsonl"
    assert workspace.project_dir == (
        tmp_path / ".dev-tools/reference-agent-runs/test-board/v1/attempt-001/project"
    )
    assert workspace.scratch_dir == workspace.project_dir.parent


def test_reference_agent_workspace_rejects_unreviewed_components(tmp_path) -> None:
    from kicad_mcp.evals.reference_agent_runner import (
        ReferenceAgentRunnerError,
        ReferenceAgentWorkspace,
    )

    for board_id, version, attempt_id in (
        ("../escape", "v1", "attempt-001"),
        ("board", "../v1", "attempt-001"),
        ("board", "v1", "../attempt-001"),
    ):
        with pytest.raises(ReferenceAgentRunnerError, match="identifier"):
            ReferenceAgentWorkspace.for_board(
                checkout_dir=tmp_path, board_id=board_id, version=version, attempt_id=attempt_id
            )


def test_reference_agent_workspace_requires_committed_prompt(tmp_path) -> None:
    from kicad_mcp.evals.reference_agent_runner import (
        ReferenceAgentRunnerError,
        ReferenceAgentWorkspace,
    )

    with pytest.raises(ReferenceAgentRunnerError, match="original prompt"):
        ReferenceAgentWorkspace.for_board(
            checkout_dir=tmp_path, board_id="board", version="v1", attempt_id="attempt-001"
        )


def test_reference_agent_workspace_reviewed_attempt_is_bounded(tmp_path) -> None:
    from kicad_mcp.evals.reference_agent_runner import (
        ReferenceAgentRunnerError,
        ReferenceAgentWorkspace,
    )

    board = tmp_path / "docs/evidence/reference-boards/esp32-c6-usbc/v1"
    board.mkdir(parents=True)
    (board / "original-prompt.md").write_text("prompt\n", encoding="utf-8")
    workspace = ReferenceAgentWorkspace.for_reviewed_attempt(
        checkout_dir=tmp_path, board_id="esp32-c6-usbc", attempt_number=2
    )
    assert workspace.version == "v1"
    assert workspace.attempt_id == "attempt-002"
    with pytest.raises(ReferenceAgentRunnerError, match="reviewed board"):
        ReferenceAgentWorkspace.for_reviewed_attempt(
            checkout_dir=tmp_path, board_id="other-board", attempt_number=1
        )
    for value in (0, 1000):
        with pytest.raises(ReferenceAgentRunnerError, match="attempt number"):
            ReferenceAgentWorkspace.for_reviewed_attempt(
                checkout_dir=tmp_path, board_id="esp32-c6-usbc", attempt_number=value
            )


def test_discover_reference_kicad_cli_requires_working_v10(tmp_path, monkeypatch) -> None:
    import kicad_mcp.evals.reference_agent_runner as runner

    v11 = tmp_path / "kicad11.exe"
    v10 = tmp_path / "kicad10.exe"
    v11.write_bytes(b"x")
    v10.write_bytes(b"x")
    monkeypatch.setattr(runner, "_reference_kicad_candidates", lambda: (v11, v10))
    monkeypatch.setattr(
        runner, "find_kicad_version", lambda path: "11.0.0" if path == v11 else "10.0.6"
    )
    assert runner.discover_reference_kicad_cli() == v10.resolve()


def test_discover_reference_kicad_cli_fails_closed_without_v10(tmp_path, monkeypatch) -> None:
    import kicad_mcp.evals.reference_agent_runner as runner

    candidate = tmp_path / "kicad.exe"
    candidate.write_bytes(b"x")
    monkeypatch.setattr(runner, "_reference_kicad_candidates", lambda: (candidate,))
    monkeypatch.setattr(runner, "find_kicad_version", lambda _path: "11.0.0")
    with pytest.raises(runner.ReferenceAgentRunnerError, match="KiCad 10"):
        runner.discover_reference_kicad_cli()


def test_reference_kicad_candidates_include_windows_v10_locations(tmp_path, monkeypatch) -> None:
    import kicad_mcp.evals.reference_agent_runner as runner

    discovered = tmp_path / "discovered.exe"
    monkeypatch.setattr(runner, "discover_kicad_cli", lambda: discovered)
    monkeypatch.setattr(runner.sys, "platform", "win32")
    candidates = runner._reference_kicad_candidates()
    assert candidates[0] == discovered
    assert Path.home() / "AppData/Local/Programs/KiCad/10.0/bin/kicad-cli.exe" in candidates
    assert Path("C:/Program Files/KiCad/10.0/bin/kicad-cli.exe") in candidates
    assert len(candidates) == len(set(candidates))


def test_reference_agent_phase_rejects_unknown_name() -> None:
    from kicad_mcp.evals.reference_agent_runner import (
        ReferenceAgentPhase,
        ReferenceAgentRunnerError,
    )

    with pytest.raises(ReferenceAgentRunnerError, match="unsupported reference-agent phase"):
        ReferenceAgentPhase.for_name("unknown")


def _write_reference_manufacturing_approval(
    workspace, *, source_revision: str, digest: str
) -> None:
    import json

    workspace.project_dir.mkdir(parents=True, exist_ok=True)
    workspace.manufacturing_approval_path.write_text(
        json.dumps(
            {
                "schema_version": "pcb-reference-manufacturing-approval.v1",
                "approved_by": "benchmark-reviewer",
                "approved_at_utc": "2026-09-10T16:00:00Z",
                "approval_scope": "manufacturing_release",
                "board_id": workspace.board_id,
                "benchmark_version": workspace.version,
                "attempt_id": workspace.attempt_id,
                "source_revision": source_revision,
                "project_state_digest": digest,
                "approved_project_files": [
                    {
                        "path": path.relative_to(workspace.project_dir).as_posix(),
                        "sha256": __import__("hashlib").sha256(path.read_bytes()).hexdigest(),
                    }
                    for path in sorted(workspace.project_dir.rglob("*"))
                    if path.is_file()
                    and (
                        path.suffix in {".kicad_pro", ".kicad_sch", ".kicad_pcb", ".kicad_dru"}
                        or path.relative_to(workspace.project_dir).as_posix()
                        == ".kicad-mcp/project_spec.json"
                    )
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )


def test_reference_manufacturing_approval_is_required_and_bound_to_project_state(tmp_path) -> None:
    from kicad_mcp.evals.reference_agent_runner import (
        ReferenceAgentRunnerError,
        compute_reference_project_state_digest,
        load_reference_manufacturing_approval,
    )

    workspace = _workspace(tmp_path, attempt_id="attempt-003")
    workspace.project_dir.mkdir(parents=True)
    (workspace.project_dir / "demo.kicad_sch").write_text("schematic\n", encoding="utf-8")
    (workspace.project_dir / "demo.kicad_pcb").write_text("board\n", encoding="utf-8")
    source_revision = "a" * 40
    digest = compute_reference_project_state_digest(workspace)

    with pytest.raises(
        ReferenceAgentRunnerError, match="manufacturing approval evidence is missing"
    ):
        load_reference_manufacturing_approval(workspace, source_revision=source_revision)

    _write_reference_manufacturing_approval(
        workspace, source_revision=source_revision, digest=digest
    )
    approval = load_reference_manufacturing_approval(workspace, source_revision=source_revision)
    assert approval.project_state_digest == digest
    assert approval.approved_by == "benchmark-reviewer"


def test_reference_manufacturing_approval_rejects_source_or_state_drift(tmp_path) -> None:
    from kicad_mcp.evals.reference_agent_runner import (
        ReferenceAgentRunnerError,
        compute_reference_project_state_digest,
        load_reference_manufacturing_approval,
    )

    workspace = _workspace(tmp_path, attempt_id="attempt-003")
    workspace.project_dir.mkdir(parents=True)
    (workspace.project_dir / "demo.kicad_sch").write_text("schematic\n", encoding="utf-8")
    board = workspace.project_dir / "demo.kicad_pcb"
    board.write_text("board-v1\n", encoding="utf-8")
    source_revision = "b" * 40
    digest = compute_reference_project_state_digest(workspace)
    _write_reference_manufacturing_approval(
        workspace, source_revision=source_revision, digest=digest
    )

    with pytest.raises(ReferenceAgentRunnerError, match="source revision"):
        load_reference_manufacturing_approval(workspace, source_revision="c" * 40)

    board.write_text("board-v2\n", encoding="utf-8")
    with pytest.raises(ReferenceAgentRunnerError, match="project state"):
        load_reference_manufacturing_approval(workspace, source_revision=source_revision)


def test_reference_manufacturing_prompt_uses_fixed_project_local_approval_path(tmp_path) -> None:
    from kicad_mcp.evals.reference_agent_runner import (
        append_reference_manufacturing_approval_instruction,
        compute_reference_project_state_digest,
        load_reference_manufacturing_approval,
    )

    workspace = _workspace(tmp_path, attempt_id="attempt-003")
    workspace.project_dir.mkdir(parents=True)
    (workspace.project_dir / "demo.kicad_sch").write_text("schematic\n", encoding="utf-8")
    (workspace.project_dir / "demo.kicad_pcb").write_text("board\n", encoding="utf-8")
    source_revision = "d" * 40
    _write_reference_manufacturing_approval(
        workspace,
        source_revision=source_revision,
        digest=compute_reference_project_state_digest(workspace),
    )
    approval = load_reference_manufacturing_approval(workspace, source_revision=source_revision)
    prompt = append_reference_manufacturing_approval_instruction("Manufacture.\n", approval)

    assert 'approval_evidence_path="reference-manufacturing-approval.json"' in prompt
    assert str(workspace.project_dir) not in prompt


def test_reference_manufacturing_approval_event_is_sanitized(tmp_path) -> None:
    from kicad_mcp.evals.reference_agent_runner import (
        compute_reference_project_state_digest,
        load_reference_manufacturing_approval,
        reference_manufacturing_approval_event,
    )

    workspace = _workspace(tmp_path, attempt_id="attempt-003")
    workspace.project_dir.mkdir(parents=True)
    (workspace.project_dir / "demo.kicad_sch").write_text("schematic\n", encoding="utf-8")
    (workspace.project_dir / "demo.kicad_pcb").write_text("board\n", encoding="utf-8")
    source_revision = "e" * 40
    _write_reference_manufacturing_approval(
        workspace,
        source_revision=source_revision,
        digest=compute_reference_project_state_digest(workspace),
    )
    approval = load_reference_manufacturing_approval(workspace, source_revision=source_revision)
    event = reference_manufacturing_approval_event(workspace, approval)

    assert event.event_type == "workflow"
    assert event.name == "human_manufacturing_approval"
    assert event.status == "completed"
    assert event.details["source_revision"] == source_revision
    assert event.details["project_state_digest"] == approval.project_state_digest


def test_reference_source_revision_rejects_dirty_runtime_source_but_not_evidence(tmp_path) -> None:
    import shutil
    import subprocess

    from kicad_mcp.evals.reference_agent_runner import (
        ReferenceAgentRunnerError,
        discover_reference_source_revision,
    )

    (tmp_path / "src").mkdir()
    (tmp_path / "scripts").mkdir()
    (tmp_path / "src/runtime.py").write_text("VALUE = 1\n", encoding="utf-8")
    (tmp_path / "scripts/runner.py").write_text("print('run')\n", encoding="utf-8")
    git_executable = shutil.which("git")
    assert git_executable is not None
    subprocess.run([git_executable, "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(
        [git_executable, "config", "user.email", "test@example.com"], cwd=tmp_path, check=True
    )
    subprocess.run([git_executable, "config", "user.name", "Test"], cwd=tmp_path, check=True)
    subprocess.run([git_executable, "add", "src", "scripts"], cwd=tmp_path, check=True)
    subprocess.run([git_executable, "commit", "-qm", "fixture"], cwd=tmp_path, check=True)
    revision = discover_reference_source_revision(tmp_path)
    assert len(revision) == 40

    evidence = tmp_path / "docs/evidence/reference-boards/board/v1/attempts/attempt-003"
    evidence.mkdir(parents=True)
    (evidence / "agent-log.jsonl").write_text("{}\n", encoding="utf-8")
    assert discover_reference_source_revision(tmp_path) == revision

    (tmp_path / "src/runtime.py").write_text("VALUE = 2\n", encoding="utf-8")
    with pytest.raises(ReferenceAgentRunnerError, match="runtime source checkout is dirty"):
        discover_reference_source_revision(tmp_path)


def test_reference_manufacturing_approval_requires_exact_approved_file_manifest(tmp_path) -> None:
    from kicad_mcp.evals.reference_agent_runner import (
        ReferenceAgentRunnerError,
        compute_reference_project_state_digest,
        load_reference_manufacturing_approval,
    )

    workspace = _workspace(tmp_path, attempt_id="attempt-003")
    workspace.project_dir.mkdir(parents=True)
    (workspace.project_dir / "demo.kicad_sch").write_text("schematic\n", encoding="utf-8")
    (workspace.project_dir / "demo.kicad_pcb").write_text("board\n", encoding="utf-8")
    source_revision = "9" * 40
    _write_reference_manufacturing_approval(
        workspace,
        source_revision=source_revision,
        digest=compute_reference_project_state_digest(workspace),
    )
    payload = json.loads(workspace.manufacturing_approval_path.read_text())
    payload["approved_project_files"][0]["sha256"] = "0" * 64
    workspace.manufacturing_approval_path.write_text(json.dumps(payload) + "\n", encoding="utf-8")

    with pytest.raises(ReferenceAgentRunnerError, match="approved project files"):
        load_reference_manufacturing_approval(workspace, source_revision=source_revision)


def test_reference_manufacturing_approval_rejects_unsafe_reviewer_before_provider(tmp_path) -> None:
    from kicad_mcp.evals.reference_agent_runner import (
        ReferenceAgentRunnerError,
        compute_reference_project_state_digest,
        load_reference_manufacturing_approval,
    )

    workspace = _workspace(tmp_path, attempt_id="attempt-003")
    workspace.project_dir.mkdir(parents=True)
    (workspace.project_dir / "demo.kicad_sch").write_text("schematic\n", encoding="utf-8")
    (workspace.project_dir / "demo.kicad_pcb").write_text("board\n", encoding="utf-8")
    source_revision = "7" * 40
    _write_reference_manufacturing_approval(
        workspace,
        source_revision=source_revision,
        digest=compute_reference_project_state_digest(workspace),
    )
    payload = json.loads(workspace.manufacturing_approval_path.read_text())
    payload["approved_by"] = "/home/private/reviewer"
    workspace.manufacturing_approval_path.write_text(json.dumps(payload) + "\n", encoding="utf-8")

    with pytest.raises(ReferenceAgentRunnerError, match="reviewer is invalid"):
        load_reference_manufacturing_approval(workspace, source_revision=source_revision)


def test_reference_manufacturing_approval_event_uses_handoff_time_not_approval_time(
    tmp_path,
) -> None:
    from datetime import UTC, datetime

    from kicad_mcp.evals.reference_agent_runner import (
        compute_reference_project_state_digest,
        load_reference_manufacturing_approval,
        reference_manufacturing_approval_event,
    )

    workspace = _workspace(tmp_path, attempt_id="attempt-003")
    workspace.project_dir.mkdir(parents=True)
    (workspace.project_dir / "demo.kicad_sch").write_text("schematic\n", encoding="utf-8")
    (workspace.project_dir / "demo.kicad_pcb").write_text("board\n", encoding="utf-8")
    source_revision = "8" * 40
    _write_reference_manufacturing_approval(
        workspace,
        source_revision=source_revision,
        digest=compute_reference_project_state_digest(workspace),
    )
    approval = load_reference_manufacturing_approval(workspace, source_revision=source_revision)
    handoff_at = datetime(2026, 9, 10, 17, 0, tzinfo=UTC)
    event = reference_manufacturing_approval_event(workspace, approval, handoff_at=handoff_at)
    assert event.timestamp == handoff_at
    assert event.details["approved_at_utc"] == "2026-09-10T16:00:00+00:00"


def test_reference_source_revision_fail_closed_error_paths(tmp_path, monkeypatch) -> None:
    import kicad_mcp.evals.reference_agent_runner as runner

    monkeypatch.setattr(runner.shutil, "which", lambda _name: None)
    with pytest.raises(runner.ReferenceAgentRunnerError, match="source revision"):
        runner.discover_reference_source_revision(tmp_path)

    monkeypatch.setattr(runner.shutil, "which", lambda _name: "/usr/bin/git")

    def raise_oserror(*_args: object, **_kwargs: object) -> None:
        raise OSError("boom")

    monkeypatch.setattr(runner.subprocess, "run", raise_oserror)
    with pytest.raises(runner.ReferenceAgentRunnerError, match="source revision"):
        runner.discover_reference_source_revision(tmp_path)

    class Result:
        def __init__(self, returncode: int, stdout: str) -> None:
            self.returncode = returncode
            self.stdout = stdout

    monkeypatch.setattr(runner.subprocess, "run", lambda *_args, **_kwargs: Result(1, "not-a-sha"))
    with pytest.raises(runner.ReferenceAgentRunnerError, match="source revision"):
        runner.discover_reference_source_revision(tmp_path)

    calls = iter((Result(0, "a" * 40), Result(1, "")))
    monkeypatch.setattr(runner.subprocess, "run", lambda *_args, **_kwargs: next(calls))
    with pytest.raises(runner.ReferenceAgentRunnerError, match="runtime source status"):
        runner.discover_reference_source_revision(tmp_path)


def test_reference_project_state_fail_closed_structure_paths(tmp_path) -> None:
    from kicad_mcp.evals.reference_agent_runner import (
        ReferenceAgentRunnerError,
        compute_reference_project_state_digest,
    )

    workspace = _workspace(tmp_path, attempt_id="attempt-003")
    with pytest.raises(ReferenceAgentRunnerError, match="state directory is missing"):
        compute_reference_project_state_digest(workspace)

    workspace.project_dir.mkdir(parents=True)
    (workspace.project_dir / "nested").mkdir()
    (workspace.project_dir / "demo.kicad_sch").write_text("schematic\n", encoding="utf-8")
    with pytest.raises(ReferenceAgentRunnerError, match="requires schematic and PCB"):
        compute_reference_project_state_digest(workspace)

    board = workspace.project_dir / "demo.kicad_pcb"
    board.write_text("board\n", encoding="utf-8")
    link = workspace.project_dir / "linked.kicad_dru"
    try:
        link.symlink_to(board.name)
    except OSError:
        pytest.skip("symlinks are not available")
    with pytest.raises(ReferenceAgentRunnerError, match="must not contain symlinks"):
        compute_reference_project_state_digest(workspace)


def test_reference_manufacturing_approval_rejects_malformed_evidence_variants(tmp_path) -> None:
    from kicad_mcp.evals.reference_agent_runner import (
        ReferenceAgentRunnerError,
        compute_reference_project_state_digest,
        load_reference_manufacturing_approval,
    )

    workspace = _workspace(tmp_path, attempt_id="attempt-003")
    workspace.project_dir.mkdir(parents=True)
    (workspace.project_dir / "demo.kicad_sch").write_text("schematic\n", encoding="utf-8")
    (workspace.project_dir / "demo.kicad_pcb").write_text("board\n", encoding="utf-8")
    source_revision = "6" * 40
    digest = compute_reference_project_state_digest(workspace)

    workspace.manufacturing_approval_path.write_text("{bad json\n", encoding="utf-8")
    with pytest.raises(ReferenceAgentRunnerError, match="evidence is invalid"):
        load_reference_manufacturing_approval(workspace, source_revision=source_revision)

    workspace.manufacturing_approval_path.write_text("[]\n", encoding="utf-8")
    with pytest.raises(ReferenceAgentRunnerError, match="must be an object"):
        load_reference_manufacturing_approval(workspace, source_revision=source_revision)

    def valid_payload() -> dict[str, object]:
        _write_reference_manufacturing_approval(
            workspace, source_revision=source_revision, digest=digest
        )
        return json.loads(workspace.manufacturing_approval_path.read_text())

    cases = [
        ("reviewer", lambda p: p.__setitem__("approved_by", ""), "reviewer is invalid"),
        ("timestamp-type", lambda p: p.__setitem__("approved_at_utc", 123), "timestamp is invalid"),
        (
            "timestamp-value",
            lambda p: p.__setitem__("approved_at_utc", "not-a-date"),
            "timestamp is invalid",
        ),
        (
            "timestamp-naive",
            lambda p: p.__setitem__("approved_at_utc", "2026-09-10T16:00:00"),
            "timezone-aware",
        ),
        (
            "files-type",
            lambda p: p.__setitem__("approved_project_files", "bad"),
            "approved project files",
        ),
        (
            "files-item",
            lambda p: p.__setitem__("approved_project_files", ["bad"]),
            "approved project files",
        ),
        (
            "files-value-type",
            lambda p: p.__setitem__("approved_project_files", [{"path": 1, "sha256": "0" * 64}]),
            "approved project files",
        ),
        (
            "files-digest",
            lambda p: p.__setitem__(
                "approved_project_files", [{"path": "demo.kicad_pcb", "sha256": "bad"}]
            ),
            "approved project files",
        ),
        (
            "tree-digest",
            lambda p: p.__setitem__("project_state_digest", "sha256:" + "0" * 64),
            "project state",
        ),
    ]
    for _label, mutate, message in cases:
        payload = valid_payload()
        mutate(payload)
        workspace.manufacturing_approval_path.write_text(
            json.dumps(payload) + "\n", encoding="utf-8"
        )
        with pytest.raises(ReferenceAgentRunnerError, match=message):
            load_reference_manufacturing_approval(workspace, source_revision=source_revision)
