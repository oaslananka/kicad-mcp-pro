"""NVIDIA NIM adapter contract tests for live model evaluations."""

from __future__ import annotations

import json
from pathlib import Path

import httpx

from kicad_mcp.evals.nvidia_nim_adapter import (
    NVIDIA_NIM_CHAT_COMPLETIONS_URL,
    build_chat_payload,
    load_eval_tool_catalog,
    request_nvidia_nim,
)


def test_catalog_is_deterministic_and_limited_to_corpus_references(tmp_path: Path) -> None:
    cases = tmp_path / "cases.yaml"
    cases.write_text(
        """\
schema_version: 2
cases:
  - id: inspect
    category: inspection
    safety: read_only
    expected_behavior: tool_calls
    prompt: Inspect the board.
    expected_tools: [pcb_get_board_summary]
    allowed_tools: [kicad_set_project]
    forbidden_tools: [pcb_delete_items]
    max_calls: 2
""",
        encoding="utf-8",
    )
    reference = tmp_path / "tools.md"
    reference.write_text(
        (
            "| Tool | Profile(s) | Read-Only | Destructive | Open-World | "
            "Idempotent | Headless | Requires KiCad Running | Summary |\n"
            "|---|---|---:|---:|---:|---:|---:|---:|---|\n"
            "| `pcb_delete_items` | full | no | yes | no | no | no | yes | "
            "Delete items by UUID. |\n"
            "| `pcb_get_board_summary` | full | yes | no | no | yes | yes | no | "
            "Summarize the current board. |\n"
            "| `kicad_set_project` | all | no | yes | no | yes | yes | no | "
            "Set the active project. |\n"
            "| `unrelated_tool` | full | yes | no | no | yes | yes | no | "
            "Must not enter the eval catalog. |\n"
        ),
        encoding="utf-8",
    )

    catalog = load_eval_tool_catalog(cases, reference)

    assert [tool.name for tool in catalog] == [
        "kicad_set_project",
        "pcb_delete_items",
        "pcb_get_board_summary",
    ]
    assert catalog[-1].summary == "Summarize the current board."


def test_chat_payload_contains_strict_classifier_contract_without_case_expectations() -> None:
    payload = build_chat_payload(
        model="nvidia/test-model",
        prompt="Summarize this PCB without changing it.",
        catalog=(
            {"name": "pcb_get_board_summary", "summary": "Summarize the board."},
            {"name": "pcb_delete_items", "summary": "Delete items."},
        ),
    )

    assert payload["model"] == "nvidia/test-model"
    assert payload["temperature"] == 0
    assert payload["stream"] is False
    schema = payload["guided_json"]
    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False
    assert schema["required"] == ["response_kind", "called_tools"]
    assert schema["properties"]["response_kind"]["enum"] == [
        "answer",
        "confirmation",
        "refusal",
        "tool_calls",
    ]
    assert schema["properties"]["called_tools"]["items"]["enum"] == [
        "pcb_delete_items",
        "pcb_get_board_summary",
    ]
    assert payload["messages"][1] == {
        "role": "user",
        "content": "Summarize this PCB without changing it.",
    }
    system = payload["messages"][0]["content"]
    assert "called_tools" in system
    assert "response_kind" in system
    assert "expected_tools" not in system
    assert "forbidden_tools" not in system


def test_nim_request_returns_only_normalized_observation_and_optional_usage() -> None:
    raw_provider_text = "provider-internal-analysis-that-must-not-escape"

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == NVIDIA_NIM_CHAT_COMPLETIONS_URL
        assert request.headers["Authorization"].startswith("Bearer ")
        payload = json.loads(request.content)
        assert payload["model"] == "nvidia/test-model"
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
                "usage": {"prompt_tokens": 120, "completion_tokens": 12},
                "provider_debug": raw_provider_text,
            },
        )

    result = request_nvidia_nim(
        model="nvidia/test-model",
        prompt="Summarize the board.",
        api_key="runtime-" + "key",
        catalog=({"name": "pcb_get_board_summary", "summary": "Summarize."},),
        transport=httpx.MockTransport(handler),
    )

    assert result["status"] == "ok"
    assert result["called_tools"] == ["pcb_get_board_summary"]
    assert result["response_kind"] == "tool_calls"
    assert result["input_tokens"] == 120
    assert result["output_tokens"] == 12
    assert result["estimated_cost_micros"] is None
    assert raw_provider_text not in json.dumps(result)


def test_nim_request_marks_missing_usage_as_unavailable_not_model_failure() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": '{"response_kind":"answer","called_tools":[]}'}}
                ]
            },
        )

    result = request_nvidia_nim(
        model="nvidia/test-model",
        prompt="Answer without a tool.",
        api_key="runtime-" + "key",
        catalog=(),
        transport=httpx.MockTransport(handler),
    )

    assert result["status"] == "ok"
    assert result["input_tokens"] is None
    assert result["output_tokens"] is None


def test_nim_request_classifies_provider_failures_without_raw_body() -> None:
    raw_body = "provider-body-that-must-not-escape"

    for status, expected in (
        (401, "provider_auth"),
        (403, "provider_auth"),
        (429, "provider_rate_limit"),
        (503, "provider_unavailable"),
        (400, "model_error"),
    ):
        result = request_nvidia_nim(
            model="nvidia/test-model",
            prompt="Inspect.",
            api_key="runtime-" + "key",
            catalog=(),
            transport=httpx.MockTransport(
                lambda _request, status=status: httpx.Response(status, text=raw_body)
            ),
        )
        assert result == {
            "schema_version": 1,
            "status": "error",
            "failure_kind": expected,
        }
        assert raw_body not in json.dumps(result)


def test_nim_request_rejects_unknown_or_malformed_model_output() -> None:
    responses = (
        "not json",
        '{"response_kind":"tool_calls","called_tools":["unknown_tool"]}',
        '{"response_kind":"answer","called_tools":["pcb_get_board_summary"]}',
    )
    for content in responses:
        result = request_nvidia_nim(
            model="nvidia/test-model",
            prompt="Inspect.",
            api_key="runtime-" + "key",
            catalog=({"name": "pcb_get_board_summary", "summary": "Summarize."},),
            transport=httpx.MockTransport(
                lambda _request, content=content: httpx.Response(
                    200,
                    json={"choices": [{"message": {"content": content}}]},
                )
            ),
        )
        assert result == {
            "schema_version": 1,
            "status": "error",
            "failure_kind": "model_error",
        }


def test_nim_request_falls_back_to_json_schema_response_format() -> None:
    requests: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        requests.append(payload)
        if len(requests) == 1:
            return httpx.Response(422, json={"error": "guided decoding unsupported"})
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": '{"response_kind":"answer","called_tools":[]}'}}
                ]
            },
        )

    result = request_nvidia_nim(
        model="nvidia/test-model",
        prompt="Answer directly.",
        api_key="test-" + "value",
        catalog=(),
        transport=httpx.MockTransport(handler),
    )

    assert result["status"] == "ok"
    assert "guided_json" in requests[0]
    assert "response_format" not in requests[0]
    assert "guided_json" not in requests[1]
    response_format = requests[1]["response_format"]
    assert response_format["type"] == "json_schema"
    assert response_format["json_schema"]["schema"]["additionalProperties"] is False


def test_nim_request_rejects_json_with_surrounding_text() -> None:
    result = request_nvidia_nim(
        model="nvidia/test-model",
        prompt="Inspect.",
        api_key="test-" + "value",
        catalog=(),
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "content": 'prefix {"response_kind":"answer","called_tools":[]}'
                            }
                        }
                    ]
                },
            )
        ),
    )

    assert result == {
        "schema_version": 1,
        "status": "error",
        "failure_kind": "model_error",
    }
