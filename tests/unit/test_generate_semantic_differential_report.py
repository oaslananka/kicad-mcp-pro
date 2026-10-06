from __future__ import annotations

import json
from pathlib import Path

from scripts import generate_semantic_differential_report as cli

SOURCE_SHA = "a" * 40
FIXTURE_HASH = "sha256:" + "b" * 64
RESULT_HASH = "sha256:" + "c" * 64


def _record(*, fixture_id: str = "clean-board") -> dict[str, object]:
    return {
        "schema_version": "kicad-semantic-differential-result.v1",
        "source_sha": SOURCE_SHA,
        "lane": "stable",
        "kicad_version": "10.0.6",
        "fixture_id": fixture_id,
        "fixture_hash": FIXTURE_HASH,
        "operation": "connectivity.net-compilation",
        "authority": "kicad-cli:netlist",
        "comparison_method": "normalized-json-sha256",
        "status": "match",
        "native_result_hash": RESULT_HASH,
        "custom_result_hash": RESULT_HASH,
        "native_pass": True,
        "custom_pass": True,
        "false_pass": False,
        "false_fail": False,
        "reason": None,
    }


def test_cli_writes_machine_readable_aggregate(tmp_path: Path) -> None:
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    output = tmp_path / "reports" / "semantic-differential.json"
    first.write_text(json.dumps(_record()) + "\n", encoding="utf-8")
    second.write_text(json.dumps(_record(fixture_id="second-board")) + "\n", encoding="utf-8")

    exit_code = cli.main(
        [
            "--result",
            str(first),
            "--result",
            str(second),
            "--json-output",
            str(output),
        ]
    )

    assert exit_code == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "kicad-semantic-differential-report.v1"
    assert payload["results_total"] == 2
    assert payload["match_count"] == 2
    assert payload["false_pass_count"] == 0
    assert payload["false_fail_count"] == 0


def test_cli_rejects_non_object_or_invalid_records(tmp_path: Path, capsys) -> None:
    record = tmp_path / "bad.json"
    output = tmp_path / "report.json"
    record.write_text("[]\n", encoding="utf-8")

    assert cli.main(["--result", str(record), "--json-output", str(output)]) == 2
    assert "must contain one JSON object" in capsys.readouterr().err
    assert not output.exists()
