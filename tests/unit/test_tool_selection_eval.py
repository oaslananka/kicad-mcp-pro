"""Tests for the tool-selection eval harness + golden dataset integrity."""

from __future__ import annotations

from pathlib import Path

import pytest

from kicad_mcp.evals.tool_selection import (
    EvalCase,
    EvalDatasetError,
    aggregate,
    all_referenced_tools,
    load_cases,
    run_eval,
    score_case,
)

CASES_PATH = Path(__file__).resolve().parents[2] / "evals" / "tool_selection" / "cases.yaml"


def _case(**kwargs: object) -> EvalCase:
    base: dict[str, object] = {
        "id": "c",
        "prompt": "do a thing",
        "expected_tools": ("run_drc",),
        "forbidden_tools": (),
    }
    base.update(kwargs)
    return EvalCase(**base)  # type: ignore[arg-type]


def test_score_full_match_passes() -> None:
    result = score_case(_case(expected_tools=("run_drc",)), ["run_drc"])
    assert result.passed
    assert result.recall == 1.0
    assert result.missing_expected == ()


def test_score_missing_expected_fails() -> None:
    result = score_case(_case(expected_tools=("run_drc", "run_erc")), ["run_drc"])
    assert not result.passed
    assert result.recall == 0.5
    assert result.missing_expected == ("run_erc",)


def test_score_forbidden_call_fails_even_with_full_recall() -> None:
    case = _case(expected_tools=("run_drc",), forbidden_tools=("pcb_delete_items",))
    result = score_case(case, ["run_drc", "pcb_delete_items"])
    assert result.recall == 1.0
    assert not result.passed
    assert result.forbidden_called == ("pcb_delete_items",)


def test_aggregate_rolls_up() -> None:
    results = [
        score_case(_case(id="a", expected_tools=("run_drc",)), ["run_drc"]),
        score_case(
            _case(id="b", expected_tools=("run_erc",), forbidden_tools=("pcb_save",)),
            ["run_erc", "pcb_save"],
        ),
    ]
    summary = aggregate(results)
    assert summary["cases"] == 2
    assert summary["passed"] == 1
    assert summary["pass_rate"] == 0.5
    assert summary["violations"] == 1


def test_run_eval_with_fake_agent() -> None:
    cases = [
        _case(id="a", prompt="p1", expected_tools=("run_drc",)),
        _case(id="b", prompt="p2", expected_tools=("run_erc",)),
    ]

    def agent(prompt: str) -> list[str]:
        return {"p1": ["run_drc"], "p2": ["pcb_save"]}.get(prompt, [])

    results = run_eval(cases, agent)
    assert [r.passed for r in results] == [True, False]


def test_load_cases_rejects_bad_datasets(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text("cases: []\n", encoding="utf-8")
    with pytest.raises(EvalDatasetError):
        load_cases(bad)

    dup = tmp_path / "dup.yaml"
    dup.write_text(
        "cases:\n"
        "  - {id: x, prompt: a, expected_tools: [run_drc]}\n"
        "  - {id: x, prompt: b, expected_tools: [run_erc]}\n",
        encoding="utf-8",
    )
    with pytest.raises(EvalDatasetError, match="Duplicate"):
        load_cases(dup)

    overlap = tmp_path / "overlap.yaml"
    overlap.write_text(
        "cases:\n  - {id: y, prompt: a, expected_tools: [run_drc], forbidden_tools: [run_drc]}\n",
        encoding="utf-8",
    )
    with pytest.raises(EvalDatasetError, match="both expected and forbidden"):
        load_cases(overlap)


def test_golden_dataset_loads() -> None:
    cases = load_cases(CASES_PATH)
    assert len(cases) >= 5
    assert all(
        case.expected_tools if case.expected_behavior == "tool_calls" else not case.expected_tools
        for case in cases
    )


def test_golden_dataset_only_references_real_tools() -> None:
    """Every expected/forbidden tool name must be a registered tool (no typos/stale)."""
    from scripts.generate_tools_reference import collect_rows

    registered = {row.name for row in collect_rows()}
    referenced = all_referenced_tools(load_cases(CASES_PATH))
    unknown = sorted(referenced - registered)
    assert unknown == [], f"Dataset references unregistered tools: {unknown}"


def test_load_cases_requires_tool_fields_to_be_lists(tmp_path: Path) -> None:
    bad = tmp_path / "bad-tool-list.yaml"
    bad.write_text(
        "cases:\n  - id: bad\n    prompt: run DRC\n    expected_tools: run_drc\n",
        encoding="utf-8",
    )

    with pytest.raises(EvalDatasetError, match="expected_tools.*list"):
        load_cases(bad)


def test_load_cases_requires_tool_list_items_to_be_strings(tmp_path: Path) -> None:
    bad = tmp_path / "bad-tool-item.yaml"
    bad.write_text(
        "cases:\n"
        "  - id: bad\n"
        "    prompt: run DRC\n"
        "    expected_tools: [run_drc]\n"
        "    forbidden_tools: [null]\n",
        encoding="utf-8",
    )

    with pytest.raises(EvalDatasetError, match="forbidden_tools.*string"):
        load_cases(bad)
