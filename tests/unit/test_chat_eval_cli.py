"""Shared subprocess CLI harness contracts for live chat-model eval adapters."""

from __future__ import annotations

import importlib.util


def test_shared_chat_eval_cli_module_exists() -> None:
    assert importlib.util.find_spec("kicad_mcp.evals.chat_eval_cli") is not None


def test_shared_chat_eval_cli_exposes_runner() -> None:
    from kicad_mcp.evals import chat_eval_cli

    assert callable(chat_eval_cli.run_chat_eval_cli)


def test_shared_runner_fails_closed_without_provider_key(monkeypatch, capsys) -> None:
    import io
    import json

    from kicad_mcp.evals.chat_eval_cli import run_chat_eval_cli

    monkeypatch.delenv("TEST_PROVIDER_KEY", raising=False)
    monkeypatch.setattr(
        "sys.stdin",
        io.StringIO('{"schema_version":1,"case_id":"x","prompt":"Inspect."}'),
    )

    exit_code = run_chat_eval_cli(
        ["--model", "test-model"],
        description="test adapter",
        api_key_env="TEST_PROVIDER_KEY",
        request_chat=lambda **_kwargs: {"status": "ok"},
        default_structured_output="none",
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert payload == {
        "failure_kind": "adapter_unavailable",
        "schema_version": 1,
        "status": "error",
    }


def test_shared_runner_delegates_strict_request(monkeypatch, capsys, tmp_path) -> None:
    import io
    import json

    from kicad_mcp.evals.chat_eval_cli import run_chat_eval_cli

    cases = tmp_path / "cases.yaml"
    cases.write_text(
        """\
schema_version: 2
cases:
  - id: inspect
    category: inspection
    safety: read_only
    expected_behavior: tool_calls
    prompt: Inspect.
    expected_tools: [pcb_get_board_summary]
    allowed_tools: []
    forbidden_tools: []
    max_calls: 1
""",
        encoding="utf-8",
    )
    tools = tmp_path / "tools.md"
    tools.write_text(
        "| Tool | Profile(s) | Read-Only | Destructive | Open-World | Idempotent | "
        "Headless | Requires KiCad Running | Summary |\n"
        "|---|---|---:|---:|---:|---:|---:|---:|---|\n"
        "| `pcb_get_board_summary` | full | yes | no | no | yes | yes | no | Summarize. |\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("TEST_PROVIDER_KEY", "dummy-test-key")
    monkeypatch.setattr(
        "sys.stdin",
        io.StringIO('{"schema_version":1,"case_id":"x","prompt":"Inspect."}'),
    )
    observed: dict[str, object] = {}

    def request_chat(**kwargs: object) -> dict[str, object]:
        observed.update(kwargs)
        return {
            "schema_version": 1,
            "status": "ok",
            "response_kind": "answer",
            "called_tools": [],
            "latency_ms": 1.0,
            "input_tokens": 2,
            "output_tokens": 1,
            "estimated_cost_micros": None,
        }

    exit_code = run_chat_eval_cli(
        [
            "--model",
            "test-model",
            "--cases",
            str(cases),
            "--tools-reference",
            str(tools),
            "--timeout-seconds",
            "17",
            "--structured-output",
            "json_schema",
        ],
        description="test adapter",
        api_key_env="TEST_PROVIDER_KEY",
        request_chat=request_chat,
        default_structured_output="none",
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["status"] == "ok"
    assert observed["model"] == "test-model"
    assert observed["prompt"] == "Inspect."
    assert observed["api_key"] == "dummy-test-key"
    assert observed["timeout_seconds"] == 17.0
    assert observed["structured_output"] == "json_schema"
    assert len(observed["catalog"]) == 1


def test_shared_runner_rejects_malformed_stdin_as_protocol_error(monkeypatch, capsys) -> None:
    import io
    import json

    from kicad_mcp.evals.chat_eval_cli import run_chat_eval_cli

    monkeypatch.setenv("TEST_PROVIDER_KEY", "dummy-test-key")
    monkeypatch.setattr(
        "sys.stdin",
        io.StringIO('{"schema_version":1,"case_id":"x","prompt":"Inspect.","extra":true}'),
    )

    exit_code = run_chat_eval_cli(
        ["--model", "test-model"],
        description="test adapter",
        api_key_env="TEST_PROVIDER_KEY",
        request_chat=lambda **_kwargs: {"status": "ok"},
        default_structured_output="none",
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert payload == {
        "failure_kind": "protocol_error",
        "schema_version": 1,
        "status": "error",
    }


def test_chat_provider_scripts_delegate_to_shared_harness() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    for relative in (
        "scripts/nvidia_nim_eval_adapter.py",
        "scripts/opencode_zen_eval_adapter.py",
        "scripts/openai_eval_adapter.py",
    ):
        text = (root / relative).read_text(encoding="utf-8")
        assert "run_chat_eval_cli" in text, relative
        assert "def _parser(" not in text, relative
        assert "json.load(sys.stdin)" not in text, relative
        assert '"failure_kind": "adapter_unavailable"' not in text, relative
        assert '"failure_kind": "protocol_error"' not in text, relative
