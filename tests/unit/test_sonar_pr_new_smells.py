"""Fail-closed policy tests require no external SonarCloud traffic."""

from __future__ import annotations

import io
import json

import pytest

from scripts.check_sonar_pr_new_smells import _new_code_smells, check_pr_new_smells, main


def _response(value: str) -> dict:
    return {
        "component": {
            "measures": [{"metric": "new_code_smells", "periods": [{"index": 1, "value": value}]}]
        }
    }


def test_zero_new_smells_accepts_public_report_without_network() -> None:
    assert check_pr_new_smells(1390, _response("0")) == 0


def test_cli_consumes_exact_stdin_report(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr("sys.argv", ["sonar-gate", "--pull-request", "1390"])
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(_response("0"))))
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
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("sys.argv", ["sonar-gate", "--pull-request", "1390"])
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(_response("0"))))
    monkeypatch.setattr("scripts.check_sonar_pr_new_smells.check_pr_new_smells", lambda *a, **kw: 5)
    assert main() == 1
    assert "zero required" in capsys.readouterr().err


def test_cli_blocks_unavailable_analysis(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.argv", ["sonar-gate", "--pull-request", "1390"])
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(_response("0"))))

    def fail(*args: object, **kwargs: object) -> int:
        raise ValueError("unknown analysis")

    monkeypatch.setattr("scripts.check_sonar_pr_new_smells.check_pr_new_smells", fail)
    assert main() == 2


@pytest.mark.parametrize("number", [0, -1])
def test_invalid_pr_number_fails(number: int) -> None:
    valid_report = _response("0")
    with pytest.raises(ValueError):
        check_pr_new_smells(number, valid_report)
