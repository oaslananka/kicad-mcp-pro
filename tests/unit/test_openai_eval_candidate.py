"""OpenAI production-capacity candidate contracts for live evals."""

from pathlib import Path

from kicad_mcp.evals.live_config import load_configurations

ROOT = Path(__file__).resolve().parents[2]
CONFIGURATIONS = ROOT / "evals/live/configurations.yaml"
WORKFLOW = ROOT / ".github/workflows/live-model-eval.yml"


def test_openai_candidate_adapter_files_exist() -> None:
    assert (ROOT / "src/kicad_mcp/evals/openai_adapter.py").is_file()
    assert (ROOT / "scripts/openai_eval_adapter.py").is_file()


def test_committed_openai_candidate_is_nonblocking_and_key_scoped() -> None:
    configurations = load_configurations(CONFIGURATIONS)
    configuration = configurations["openai-gpt-5.4-mini-2026-03-17"]

    assert configuration.host == "openai"
    assert configuration.model == "gpt-5.4-mini-2026-03-17"
    assert configuration.required_env == ("OPENAI_KEY",)
    assert configuration.command == (
        "python",
        "scripts/openai_eval_adapter.py",
        "--model",
        "gpt-5.4-mini-2026-03-17",
        "--structured-output",
        "json_schema",
    )
    assert configuration.limits.timeout_seconds == 70
    assert configuration.limits.max_retries == 2
    assert configuration.limits.max_total_cost_micros == 2_000_000


def test_manual_live_eval_workflow_exposes_only_the_openai_candidate_key() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "OPENAI_KEY: ${{ secrets.OPENAI_KEY }}" in workflow
    release_gate = (ROOT / ".github/workflows/live-model-release-gate.yml").read_text(
        encoding="utf-8"
    )
    assert "openai-gpt-5.4-mini-2026-03-17" not in release_gate
    assert "OPENAI_KEY" not in release_gate


def test_openai_adapter_exposes_only_the_reviewed_snapshot() -> None:
    from kicad_mcp.evals import openai_adapter

    assert (
        openai_adapter.OPENAI_CHAT_COMPLETIONS_URL == "https://api.openai.com/v1/chat/completions"
    )
    assert openai_adapter.OPENAI_EVAL_MODELS == frozenset({"gpt-5.4-mini-2026-03-17"})
    assert callable(openai_adapter.request_openai)


def test_openai_cli_exposes_a_main_entrypoint() -> None:
    import scripts.openai_eval_adapter as openai_cli

    assert callable(openai_cli.main)


def test_openai_request_uses_fixed_gpt5_profile_and_sanitizes_response() -> None:
    import json

    import httpx

    from kicad_mcp.evals.openai_adapter import request_openai

    raw_provider_text = "private-openai-debug"

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://api.openai.com/v1/chat/completions"
        assert request.headers["Authorization"].startswith("Bearer ")
        payload = json.loads(request.content)
        assert payload["model"] == "gpt-5.4-mini-2026-03-17"
        assert payload["max_completion_tokens"] == 1024
        assert payload["reasoning_effort"] == "none"
        assert payload["stream"] is False
        assert "max_tokens" not in payload
        assert "temperature" not in payload
        assert "top_p" not in payload
        assert payload["response_format"]["type"] == "json_schema"
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "response_kind": "tool_calls",
                                    "called_tools": ["pcb_get_board_summary"],
                                },
                                separators=(",", ":"),
                            ),
                            "debug": raw_provider_text,
                        }
                    }
                ],
                "usage": {"prompt_tokens": 20, "completion_tokens": 5},
                "debug": raw_provider_text,
            },
        )

    result = request_openai(
        model="gpt-5.4-mini-2026-03-17",
        prompt="Summarize the board.",
        api_key="dummy-test-key",
        catalog=({"name": "pcb_get_board_summary", "summary": "Summarize."},),
        transport=httpx.MockTransport(handler),
        structured_output="json_schema",
    )

    assert result["status"] == "ok"
    assert result["called_tools"] == ["pcb_get_board_summary"]
    assert result["input_tokens"] == 20
    assert result["output_tokens"] == 5
    assert raw_provider_text not in json.dumps(result)


def test_openai_request_rejects_unreviewed_model_before_network() -> None:
    import httpx
    import pytest

    from kicad_mcp.evals.openai_adapter import request_openai

    transport = httpx.MockTransport(lambda _request: pytest.fail("network called"))

    with pytest.raises(ValueError, match="reviewed OpenAI eval model"):
        request_openai(
            model="gpt-5-mini",
            prompt="Inspect.",
            api_key="dummy-test-key",
            catalog=(),
            transport=transport,
        )


def test_openai_cli_fails_closed_without_key(monkeypatch, capsys) -> None:
    import io
    import json

    import scripts.openai_eval_adapter as openai_cli

    monkeypatch.delenv("OPENAI_KEY", raising=False)
    monkeypatch.setattr(
        "sys.stdin",
        io.StringIO('{"schema_version":1,"case_id":"x","prompt":"Inspect."}'),
    )

    exit_code = openai_cli.main(["--model", "gpt-5.4-mini-2026-03-17"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert payload == {
        "failure_kind": "adapter_unavailable",
        "schema_version": 1,
        "status": "error",
    }


def test_openai_cli_delegates_valid_request_without_exposing_key(monkeypatch, capsys) -> None:
    import io
    import json

    import scripts.openai_eval_adapter as openai_cli

    monkeypatch.setenv("OPENAI_KEY", "dummy-test-key")
    monkeypatch.setattr(
        "sys.stdin",
        io.StringIO('{"schema_version":1,"case_id":"x","prompt":"Inspect."}'),
    )
    observed: dict[str, object] = {}

    def fake_request_openai(**kwargs: object) -> dict[str, object]:
        observed.update(kwargs)
        return {
            "schema_version": 1,
            "status": "ok",
            "response_kind": "answer",
            "called_tools": [],
            "latency_ms": 1.0,
            "input_tokens": 3,
            "output_tokens": 2,
            "estimated_cost_micros": None,
        }

    monkeypatch.setattr(openai_cli, "request_openai", fake_request_openai, raising=False)
    monkeypatch.setattr(openai_cli, "load_eval_tool_catalog", lambda *_args: (), raising=False)

    exit_code = openai_cli.main(["--model", "gpt-5.4-mini-2026-03-17"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["status"] == "ok"
    assert observed["model"] == "gpt-5.4-mini-2026-03-17"
    assert observed["api_key"] == "dummy-test-key"
    assert observed["structured_output"] == "json_schema"
