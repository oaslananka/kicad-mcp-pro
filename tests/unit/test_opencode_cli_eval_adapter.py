"""OpenCode CLI adapter contract tests for protected live evaluations."""

from __future__ import annotations

import json
import subprocess

import pytest

import scripts.opencode_cli_eval_adapter as cli_script
from kicad_mcp.evals.opencode_cli_adapter import (
    OPENCODE_CLI_AGENT_ID,
    OPENCODE_CLI_PROVIDER_ID,
    OPENCODE_CLI_VERSION,
    build_classifier_messages,
    build_opencode_config,
    parse_opencode_events,
    request_opencode_cli,
)


def _events(*, text: str = '{"response_kind":"answer","called_tools":[]}') -> str:
    return "\n".join(
        (
            json.dumps({"type": "step_start", "part": {"type": "step-start"}}),
            json.dumps(
                {
                    "type": "text",
                    "part": {"type": "text", "text": text[: len(text) // 2]},
                }
            ),
            json.dumps(
                {
                    "type": "text",
                    "part": {"type": "text", "text": text[len(text) // 2 :]},
                }
            ),
            json.dumps(
                {
                    "type": "step_finish",
                    "part": {
                        "type": "step-finish",
                        "reason": "stop",
                        "tokens": {"input": 20, "output": 5, "reasoning": 0},
                        "cost": 0,
                    },
                }
            ),
        )
    )


def test_opencode_cli_version_is_pinned() -> None:
    assert OPENCODE_CLI_VERSION == "1.18.10"


def test_config_uses_one_custom_provider_agent_and_denies_every_permission() -> None:
    config = build_opencode_config(
        model="nemotron-3-ultra-free",
        system_prompt="STRICT_SYSTEM_POLICY",
    )

    assert config["enabled_providers"] == [OPENCODE_CLI_PROVIDER_ID]
    assert config["permission"] == "deny"
    assert config["model"] == f"{OPENCODE_CLI_PROVIDER_ID}/nemotron-3-ultra-free"
    provider = config["provider"][OPENCODE_CLI_PROVIDER_ID]  # type: ignore[index]
    assert provider["npm"] == "@ai-sdk/openai-compatible"
    assert provider["options"] == {
        "baseURL": "https://opencode.ai/zen/v1",
        "apiKey": "{env:OPENCODE_ZEN_API_KEY}",
    }
    agent = config["agent"][OPENCODE_CLI_AGENT_ID]  # type: ignore[index]
    assert agent == {
        "description": "Strict KiCad MCP tool-selection classifier.",
        "mode": "primary",
        "model": f"{OPENCODE_CLI_PROVIDER_ID}/nemotron-3-ultra-free",
        "prompt": "STRICT_SYSTEM_POLICY",
        "temperature": 0,
        "permission": "deny",
    }
    assert "test-key" not in json.dumps(config)


def test_classifier_messages_separate_policy_from_user_request() -> None:
    system, user = build_classifier_messages(
        model="nemotron-3-ultra-free",
        prompt="Please inspect the current PCB.",
        catalog=({"name": "pcb_get_board_summary", "summary": "Summarize the board."},),
    )

    assert "TOOL_CATALOG=" in system
    assert "pcb_get_board_summary" in system
    assert "Please inspect the current PCB." not in system
    assert user == "Please inspect the current PCB."
    assert "expected_tools" not in system
    assert "forbidden_tools" not in system


def test_event_parser_retains_only_text_tokens_and_cost() -> None:
    event = parse_opencode_events(_events())

    assert event.text == '{"response_kind":"answer","called_tools":[]}'
    assert event.input_tokens == 20
    assert event.output_tokens == 5
    assert event.estimated_cost_micros == 0


@pytest.mark.parametrize(
    "stdout",
    [
        "not-json",
        json.dumps({"type": "tool", "part": {"type": "tool"}}),
        json.dumps({"type": "text", "part": {"type": "text", "text": "{}"}}),
        "\n".join(
            (
                json.dumps({"type": "step_start", "part": {"type": "step-start"}}),
                json.dumps({"type": "step_finish", "part": {"type": "step-finish", "tokens": {}}}),
            )
        ),
    ],
)
def test_event_parser_fails_closed_on_unknown_or_incomplete_stream(stdout: str) -> None:
    with pytest.raises((json.JSONDecodeError, ValueError)):
        parse_opencode_events(stdout)


def test_request_runs_pure_headless_cli_with_isolated_environment() -> None:
    captured: dict[str, object] = {}

    def runner(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        captured["command"] = command
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(command, 0, stdout=_events(), stderr="private-stderr")

    result = request_opencode_cli(
        model="nemotron-3-ultra-free",
        prompt="Answer directly.",
        api_key="test-" + "key",
        catalog=(),
        opencode_bin="/opt/opencode",
        run_process=runner,
    )

    assert result["status"] == "ok"
    assert result["response_kind"] == "answer"
    assert result["called_tools"] == []
    assert result["input_tokens"] == 20
    assert result["output_tokens"] == 5
    command = captured["command"]
    assert isinstance(command, list)
    assert command[:6] == ["/opt/opencode", "run", "--pure", "--format", "json", "--title"]
    assert "--auto" not in command
    assert command[command.index("--model") + 1] == (
        f"{OPENCODE_CLI_PROVIDER_ID}/nemotron-3-ultra-free"
    )
    assert command[command.index("--agent") + 1] == OPENCODE_CLI_AGENT_ID
    assert "Answer directly." not in command
    kwargs = captured["kwargs"]
    assert isinstance(kwargs, dict)
    env = kwargs["env"]
    assert isinstance(env, dict)
    assert env["OPENCODE_ZEN_API_KEY"] == "test-key"
    config = json.loads(env["OPENCODE_CONFIG_CONTENT"])
    assert config["permission"] == "deny"
    assert "TOOL_CATALOG=" in config["agent"][OPENCODE_CLI_AGENT_ID]["prompt"]
    assert "Answer directly." not in config["agent"][OPENCODE_CLI_AGENT_ID]["prompt"]
    assert "GITHUB_TOKEN" not in env
    assert "NVIDIA_API_KEY" not in env
    assert kwargs["input"] == "Answer directly."
    assert kwargs["capture_output"] is True
    assert kwargs["check"] is False


def test_request_applies_existing_policy_postconditions() -> None:
    def runner(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=_events(text='{"response_kind":"answer","called_tools":[]}'),
            stderr="",
        )

    result = request_opencode_cli(
        model="nemotron-3-ultra-free",
        prompt="Summarize the board.",
        api_key="test-" + "key",
        catalog=({"name": "pcb_get_board_summary", "summary": "Summarize the board."},),
        run_process=runner,
    )

    assert result["response_kind"] == "tool_calls"
    assert result["called_tools"] == ["pcb_get_board_summary"]


def test_request_classifies_missing_binary_timeout_nonzero_and_invalid_output() -> None:
    def missing(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        raise FileNotFoundError

    def timeout(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(cmd="opencode", timeout=1)

    def nonzero(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 1, stdout="", stderr="private-provider-error")

    def invalid(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 0, stdout=_events(text="not-json"), stderr="")

    common = {
        "model": "nemotron-3-ultra-free",
        "prompt": "Inspect.",
        "api_key": "test-key",
        "catalog": (),
    }
    assert (
        request_opencode_cli(**common, run_process=missing)["failure_kind"] == "adapter_unavailable"
    )
    assert request_opencode_cli(**common, run_process=timeout)["failure_kind"] == "timeout"
    assert (
        request_opencode_cli(**common, run_process=nonzero)["failure_kind"]
        == "provider_unavailable"
    )
    assert (
        request_opencode_cli(**common, run_process=invalid)["failure_kind"]
        == "model_output_invalid"
    )


def test_request_rejects_unreviewed_model_and_missing_key() -> None:
    with pytest.raises(ValueError, match="reviewed OpenCode Zen free model"):
        request_opencode_cli(model="big-pickle", prompt="Inspect.", api_key="x", catalog=())

    result = request_opencode_cli(
        model="nemotron-3-ultra-free",
        prompt="Inspect.",
        api_key="",
        catalog=(),
    )
    assert result["failure_kind"] == "adapter_unavailable"


def test_cli_script_fails_closed_without_key(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("OPENCODE_ZEN_API_KEY", raising=False)
    monkeypatch.setattr(
        "sys.stdin",
        __import__("io").StringIO('{"schema_version":1,"case_id":"x","prompt":"Inspect."}'),
    )

    exit_code = cli_script.main(["--model", "nemotron-3-ultra-free"])

    assert exit_code == 1
    assert json.loads(capsys.readouterr().out) == {
        "failure_kind": "adapter_unavailable",
        "schema_version": 1,
        "status": "error",
    }
