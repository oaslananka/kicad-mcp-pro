from pathlib import Path

from kicad_mcp.tools.validation import (
    _erc_report_payload,
    _erc_severity_summary,
    _erc_violations,
    _report_entry_finding,
)


def test_finding_metadata_extraction() -> None:
    entry: dict[str, object] = {
        "type": "err_type",
        "description": "an error",
        "severity": "error",
        "sheet_path": "/Sheet1/",
        "items": [
            {"uuid": "1234", "ref": "R1", "pin": "1", "net": "GND", "position": [10.0, 20.0]},
            {"uuid": "5678", "ref": "C1", "pin": "2", "position": [30.0, 40.0]},
        ],
    }

    finding = _report_entry_finding("erc", entry, fix_tool="run_erc")
    assert finding.metadata["sheet_path"] == "/Sheet1/"
    assert finding.metadata["refs"] == ["R1", "C1"]
    assert finding.metadata["pins"] == ["1", "2"]
    assert finding.metadata["nets"] == ["GND"]
    assert finding.metadata["uuids"] == ["1234", "5678"]
    assert finding.metadata["positions"] == [[10.0, 20.0], [30.0, 40.0]]


def test_erc_violations_preserves_sheet_path() -> None:
    report: dict[str, object] = {
        "sheets": [
            {
                "path": "/Subsheet/",
                "name": "Subsheet",
                "violations": [{"type": "err_type", "description": "an error"}],
            }
        ]
    }

    violations = _erc_violations(report)
    assert len(violations) == 1
    assert violations[0]["sheet_path"] == "/Subsheet/"

    # Check that name is used as fallback if path is absent
    report2: dict[str, object] = {
        "sheets": [
            {
                "name": "AnotherSheet",
                "violations": [
                    {
                        "type": "err_type2",
                    }
                ],
            }
        ]
    }
    violations2 = _erc_violations(report2)
    assert len(violations2) == 1
    assert violations2[0]["sheet_path"] == "AnotherSheet"


def test_erc_severity_summary_counts_by_severity() -> None:
    violations: list[dict[str, object]] = [
        {"severity": "error", "description": "a"},
        {"severity": "warning", "description": "b"},
        {"severity": "error", "description": "c"},
        {"severity": "exclusion", "description": "d"},  # other severities surface too
        {"description": "e"},  # missing severity defaults to error
    ]

    summary = _erc_severity_summary(violations)

    assert summary == {"error": 3, "warning": 1, "exclusion": 1}


def test_erc_payload_aggregates_flat_violations_and_summary() -> None:
    report: dict[str, object] = {
        "sheets": [
            {
                "path": "/",
                "violations": [
                    {"type": "t1", "severity": "error", "description": "root err"},
                ],
            },
            {
                "path": "/Sub/",
                "violations": [
                    {"type": "t2", "severity": "warning", "description": "sub warn"},
                    {"type": "t3", "severity": "error", "description": "sub err"},
                ],
            },
        ]
    }

    payload = _erc_report_payload(Path("erc_report.json"), report, None, save_report=False)

    # Flat top-level violations list aggregates across every sheet, retaining sheet identity.
    flat: list[dict[str, object]] = payload.metadata["violations"]
    assert isinstance(flat, list)
    assert len(flat) == 3
    assert {v["sheet_path"] for v in flat} == {"/", "/Sub/"}
    assert {v["description"] for v in flat} == {"root err", "sub warn", "sub err"}

    # Summary counts by severity; existing scalar preserved under violation_count.
    assert payload.metadata["summary"] == {"error": 2, "warning": 1}
    assert payload.metadata["violation_count"] == 3
    assert payload.verdict == "FAIL"


def test_erc_payload_clean_schematic_has_empty_violations_and_summary() -> None:
    report: dict[str, object] = {"sheets": [{"path": "/", "violations": []}]}

    payload = _erc_report_payload(Path("erc_report.json"), report, None, save_report=False)

    assert payload.metadata["violations"] == []
    assert payload.metadata["summary"] == {}
    assert payload.metadata["violation_count"] == 0
    assert payload.verdict == "PASS"
