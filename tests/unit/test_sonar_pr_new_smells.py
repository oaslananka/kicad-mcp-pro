"""Fail-closed policy tests require no external SonarCloud traffic."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from scripts.check_sonar_pr_new_smells import (
    _analyzed_pr_sha,
    _new_code_smells,
    check_pr_new_smells,
    main,
)


def _response(value: str) -> dict:
    return {
        "component": {
            "measures": [{"metric": "new_code_smells", "periods": [{"index": 1, "value": value}]}]
        }
    }


_HEAD_SHA = "a" * 40
_OTHER_SHA = "b" * 40


def _metadata(sha: str = _HEAD_SHA, pr: str = "1390") -> dict:
    return {
        "pullRequests": [
            {
                "key": pr,
                "analysisDate": "2026-10-21T20:34:30+0000",
                "commit": {"sha": sha},
            }
        ]
    }


def _check(
    number: int, report: object, *, before: object | None = None, after: object | None = None
) -> int:
    return check_pr_new_smells(
        number,
        report,
        expected_sha=_HEAD_SHA,
        before=_metadata() if before is None else before,
        after=_metadata() if after is None else after,
    )


def _configure_cli(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    before = tmp_path / "before.json"
    after = tmp_path / "after.json"
    before.write_text(json.dumps(_metadata()), encoding="utf-8")
    after.write_text(json.dumps(_metadata()), encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        [
            "sonar-gate",
            "--pull-request",
            "1390",
            "--expected-sha",
            _HEAD_SHA,
            "--before",
            str(before),
            "--after",
            str(after),
        ],
    )
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(_response("0"))))


def test_zero_new_smells_accepts_public_report_without_network() -> None:
    assert _check(1390, _response("0")) == 0


def test_cli_consumes_exact_stdin_report(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    _configure_cli(monkeypatch, tmp_path)
    assert main() == 0
    assert "0 new Code Smells" in capsys.readouterr().out


def test_sonarqube_single_period_response_is_supported() -> None:
    result = {"component": {"measures": [{"metric": "new_code_smells", "period": {"value": "0"}}]}}
    assert _new_code_smells(result) == 0


def test_mixed_period_shapes_fail_closed() -> None:
    mixed = _response("0")
    mixed["component"]["measures"][0]["period"] = {"value": "0"}
    with pytest.raises(ValueError, match="ambiguous"):
        _new_code_smells(mixed)


@pytest.mark.parametrize("value", ["1", "5", "16"])
def test_nonzero_new_smells_detected(value: str) -> None:
    assert _new_code_smells(_response(value)) == int(value)


@pytest.mark.parametrize(
    "data",
    [
        {},
        [],
        {"component": {}},
        {"component": {"measures": []}},
        {"component": {"measures": [{"metric": "new_code_smells", "periods": []}]}},
        {"component": {"measures": [{"metric": "new_code_smells", "periods": [{"value": "-1"}]}]}},
        {"component": {"measures": [{"metric": "new_code_smells", "periods": [{"value": 0}]}]}},
        {
            "component": {
                "measures": [
                    {"metric": "new_code_smells", "periods": [{"value": "0"}, {"value": "5"}]}
                ]
            }
        },
    ],
)
def test_unknown_or_ambiguous_analyses_fail_closed(data: object) -> None:
    with pytest.raises(ValueError):
        _new_code_smells(data)


def test_cli_blocks_new_smells(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    _configure_cli(monkeypatch, tmp_path)
    monkeypatch.setattr("scripts.check_sonar_pr_new_smells.check_pr_new_smells", lambda *a, **kw: 5)
    assert main() == 1
    assert "zero required" in capsys.readouterr().err


def test_cli_blocks_unavailable_analysis(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _configure_cli(monkeypatch, tmp_path)

    def fail(*args: object, **kwargs: object) -> int:
        raise ValueError("unknown analysis")

    monkeypatch.setattr("scripts.check_sonar_pr_new_smells.check_pr_new_smells", fail)
    assert main() == 2


@pytest.mark.parametrize("number", [0, -1])
def test_invalid_pr_number_fails(number: int) -> None:
    valid_report = _response("0")
    with pytest.raises(ValueError):
        _check(number, valid_report)


def test_confirmed_git_head_is_required_even_when_zero_smells() -> None:
    report = _response("0")
    stale = _metadata(_OTHER_SHA)
    with pytest.raises(ValueError, match="does not match"):
        _check(1390, report, before=stale)
    with pytest.raises(ValueError, match="changed while"):
        _check(1390, report, after=stale)


def test_correct_revision_nonzero_smells_still_refused() -> None:
    assert _check(1390, _response("5")) == 5


@pytest.mark.parametrize(
    "record",
    [
        {},
        [],
        {"pullRequests": []},
        {"pullRequests": [{"key": "1390", "analysisDate": "today"}]},
        {"pullRequests": [{"key": "1390", "commit": {"sha": _HEAD_SHA}}]},
        {"pullRequests": [{"key": "1390", "analysisDate": "today", "commit": {"sha": "invalid"}}]},
        {
            "pullRequests": [
                {"key": "1390", "analysisDate": "today", "commit": {"sha": _HEAD_SHA}},
                {"key": "1390", "analysisDate": "today", "commit": {"sha": _HEAD_SHA}},
            ]
        },
    ],
)
def test_missing_or_ambiguous_pr_identity_fails_closed(record: object) -> None:
    with pytest.raises(ValueError):
        _analyzed_pr_sha(record, 1390)


def test_rejects_stale_sonar_analysis_for_specific_git_sha() -> None:
    report = _response("0")
    stale = _metadata(_OTHER_SHA)
    with pytest.raises(ValueError, match="does not match"):
        _check(1390, report, before=stale)


@pytest.mark.parametrize("sha", ["bad", "A" * 40, "c" * 39, "z" * 40])
def test_expected_sha_must_be_exact_lowercase_full_hash(sha: str) -> None:
    report = _response("0")
    metadata = _metadata()
    with pytest.raises(ValueError, match="valid PR number and exact"):
        check_pr_new_smells(
            1390,
            report,
            expected_sha=sha,
            before=metadata,
            after=metadata,
        )
