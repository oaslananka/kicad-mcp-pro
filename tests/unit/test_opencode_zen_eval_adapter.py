"""OpenCode Zen adapter contract tests for experimental live evals."""

from __future__ import annotations

import json

import httpx
import pytest

import scripts.opencode_zen_eval_adapter as opencode_cli
from kicad_mcp.evals.opencode_zen_adapter import (
    OPENCODE_ZEN_CHAT_COMPLETIONS_URL,
    OPENCODE_ZEN_FREE_MODELS,
    OPENCODE_ZEN_PAID_MODELS,
    request_opencode_zen,
)


def test_opencode_request_uses_fixed_endpoint_and_sanitizes_response() -> None:
    raw_provider_text = "private-provider-debug"

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == OPENCODE_ZEN_CHAT_COMPLETIONS_URL
        assert request.headers["Authorization"].startswith("Bearer ")
        payload = json.loads(request.content)
        assert payload["model"] == "deepseek-v4-flash-free"
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"response_kind":"tool_calls",'
                                '"called_tools":["pcb_get_board_summary"]}'
                            ),
                            "reasoning_content": raw_provider_text,
                        }
                    }
                ],
                "usage": {"prompt_tokens": 20, "completion_tokens": 5},
                "debug": raw_provider_text,
            },
        )

    result = request_opencode_zen(
        model="deepseek-v4-flash-free",
        prompt="Summarize the board.",
        api_key="test-" + "key",
        catalog=({"name": "pcb_get_board_summary", "summary": "Summarize."},),
        transport=httpx.MockTransport(handler),
    )

    assert result["status"] == "ok"
    assert result["called_tools"] == ["pcb_get_board_summary"]
    assert result["input_tokens"] == 20
    assert result["output_tokens"] == 5
    assert raw_provider_text not in json.dumps(result)


def test_opencode_free_model_allowlist_matches_reviewed_experimental_set() -> None:
    assert OPENCODE_ZEN_FREE_MODELS == frozenset(
        {
            "deepseek-v4-flash-free",
            "mimo-v2.5-free",
            "laguna-s-2.1-free",
            "ling-3.0-flash-free",
            "north-mini-code-free",
            "nemotron-3-ultra-free",
        }
    )


def test_opencode_paid_model_allowlist_includes_minimax_m3() -> None:
    assert OPENCODE_ZEN_PAID_MODELS == frozenset({"minimax-m3"})


def test_opencode_paid_minimax_uses_reviewed_non_thinking_profile() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["model"] == "minimax-m3"
        assert payload["chat_template_kwargs"] == {"thinking_mode": "disabled"}
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": '{"response_kind":"answer","called_tools":[]}'}}
                ],
                "usage": {"prompt_tokens": 20, "completion_tokens": 5},
            },
        )

    result = request_opencode_zen(
        model="minimax-m3",
        prompt="Explain the design.",
        api_key="placeholder-key",
        catalog=(),
        transport=httpx.MockTransport(handler),
    )

    assert result["status"] == "ok"
    assert result["response_kind"] == "answer"


def test_opencode_request_rejects_unreviewed_model_before_network() -> None:
    with pytest.raises(ValueError, match="reviewed OpenCode Zen chat model"):
        request_opencode_zen(
            model="big-pickle",
            prompt="Inspect.",
            api_key="test-" + "key",
            catalog=(),
            transport=httpx.MockTransport(lambda _request: pytest.fail("network called")),
        )


def test_opencode_cli_fails_closed_without_key(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("OPENCODE_ZEN_API_KEY", raising=False)
    monkeypatch.setattr(
        "sys.stdin",
        __import__("io").StringIO('{"schema_version":1,"case_id":"x","prompt":"Inspect."}'),
    )

    exit_code = opencode_cli.main(["--model", "deepseek-v4-flash-free"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert payload == {
        "failure_kind": "adapter_unavailable",
        "schema_version": 1,
        "status": "error",
    }
