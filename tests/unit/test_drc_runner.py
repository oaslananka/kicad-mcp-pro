from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from kicad_mcp.validation.drc_runner import (
    DrcRunResult,
    classify_drc_report,
    run_drc_report,
)


def test_classify_drc_report_distinguishes_clean_findings_and_malformed() -> None:
    clean = classify_drc_report({"violations": [], "unconnected_items": []})
    findings = classify_drc_report(
        {
            "violations": [{"type": "clearance"}],
            "unconnected_items": [],
        }
    )
    malformed_list = classify_drc_report({"violations": "not-a-list", "unconnected_items": []})
    malformed_entry = classify_drc_report({"violations": [None], "unconnected_items": []})
    missing_required = classify_drc_report({"unconnected_items": []})

    assert clean == ("clean", None)
    assert findings == ("findings", None)
    assert malformed_list == (
        "malformed",
        "DRC report field 'violations' must be a list.",
    )
    assert malformed_entry == (
        "malformed",
        "DRC report field 'violations' must contain only objects.",
    )
    assert missing_required == (
        "malformed",
        "DRC report is missing required field 'violations'.",
    )


def test_run_drc_report_rejects_missing_board_input_without_invoking_cli(
    tmp_path: Path,
) -> None:
    def must_not_run(_variants: list[list[str]]) -> tuple[int, str, str]:
        raise AssertionError("CLI must not run without a PCB input file")

    result = run_drc_report(
        "drc.json",
        pcb_file=tmp_path / "missing.kicad_pcb",
        output_dir=tmp_path,
        run_cli_variants=must_not_run,
        capabilities=SimpleNamespace(
            supports_drc_severity_all=False,
            supports_drc_exit_code_violations=False,
        ),
    )

    assert result.status == "unavailable"
    assert result.return_code is None
    assert result.report is None
    assert result.error == "PCB input file is unavailable or does not exist."


def test_run_drc_report_classifies_zero_exit_clean_report(tmp_path: Path) -> None:
    pcb_file = tmp_path / "board.kicad_pcb"
    pcb_file.write_text("(kicad_pcb)", encoding="utf-8")

    def run_variants(variants: list[list[str]]) -> tuple[int, str, str]:
        report_path = Path(variants[0][variants[0].index("--output") + 1])
        report_path.write_text(
            json.dumps({"violations": [], "unconnected_items": []}),
            encoding="utf-8",
        )
        return 0, "completed", ""

    result = run_drc_report(
        "drc.json",
        pcb_file=pcb_file,
        output_dir=tmp_path,
        run_cli_variants=run_variants,
        capabilities=SimpleNamespace(
            supports_drc_severity_all=False,
            supports_drc_exit_code_violations=False,
        ),
    )

    assert result.status == "clean"
    assert result.return_code == 0
    assert result.report == {"violations": [], "unconnected_items": []}
    assert result.error is None


def test_run_drc_report_owns_variant_fallback_and_preserves_design_findings(
    tmp_path: Path,
) -> None:
    pcb_file = tmp_path / "board.kicad_pcb"
    pcb_file.write_text("(kicad_pcb)", encoding="utf-8")
    captured: list[list[str]] = []

    def run_variants(variants: list[list[str]]) -> tuple[int, str, str]:
        assert len(variants) == 1
        command = variants[0]
        captured.append(command)
        if len(captured) == 1:
            return 2, "", "unsupported positional syntax"
        report_path = Path(command[command.index("--output") + 1])
        report_path.write_text(
            json.dumps(
                {
                    "violations": [{"type": "clearance"}],
                    "unconnected_items": [],
                }
            ),
            encoding="utf-8",
        )
        return 5, "", "violations found"

    result = run_drc_report(
        "drc.json",
        pcb_file=pcb_file,
        output_dir=tmp_path,
        run_cli_variants=run_variants,
        capabilities=SimpleNamespace(
            supports_drc_severity_all=True,
            supports_drc_exit_code_violations=True,
        ),
    )

    assert result.status == "findings"
    assert result.return_code == 5
    assert result.report is not None
    assert result.error is None
    assert captured == [
        [
            "pcb",
            "drc",
            "--output",
            str(tmp_path / "drc.json"),
            "--format",
            "json",
            "--severity-all",
            "--exit-code-violations",
            str(pcb_file),
        ],
        [
            "pcb",
            "drc",
            "--input",
            str(pcb_file),
            "--output",
            str(tmp_path / "drc.json"),
            "--format",
            "json",
            "--severity-all",
            "--exit-code-violations",
        ],
    ]


def test_run_drc_report_rejects_nonzero_clean_result(tmp_path: Path) -> None:
    pcb_file = tmp_path / "board.kicad_pcb"
    pcb_file.write_text("(kicad_pcb)", encoding="utf-8")

    def run_variants(variants: list[list[str]]) -> tuple[int, str, str]:
        report_path = Path(variants[0][variants[0].index("--output") + 1])
        report_path.write_text(
            json.dumps({"violations": [], "unconnected_items": []}),
            encoding="utf-8",
        )
        return 2, "", "command failed"

    result = run_drc_report(
        "drc.json",
        pcb_file=pcb_file,
        output_dir=tmp_path,
        run_cli_variants=run_variants,
        capabilities=SimpleNamespace(
            supports_drc_severity_all=False,
            supports_drc_exit_code_violations=False,
        ),
    )

    assert result.status == "unavailable"
    assert result.report is None
    assert result.error == "DRC command failed with exit code 2: command failed"


def test_run_drc_report_removes_stale_output_and_reports_missing_output(tmp_path: Path) -> None:
    pcb_file = tmp_path / "board.kicad_pcb"
    pcb_file.write_text("(kicad_pcb)", encoding="utf-8")
    stale = tmp_path / "drc.json"
    stale.write_text(json.dumps({"violations": [], "unconnected_items": []}), encoding="utf-8")

    result = run_drc_report(
        "drc.json",
        pcb_file=pcb_file,
        output_dir=tmp_path,
        run_cli_variants=lambda _variants: (1, "", "cli unavailable"),
        capabilities=SimpleNamespace(
            supports_drc_severity_all=False,
            supports_drc_exit_code_violations=False,
        ),
    )

    assert result.status == "unavailable"
    assert result.report is None
    assert result.error == "cli unavailable"
    assert not stale.exists()


def test_run_drc_report_classifies_invalid_json_as_malformed(tmp_path: Path) -> None:
    pcb_file = tmp_path / "board.kicad_pcb"
    pcb_file.write_text("(kicad_pcb)", encoding="utf-8")

    def run_variants(variants: list[list[str]]) -> tuple[int, str, str]:
        report_path = Path(variants[0][variants[0].index("--output") + 1])
        report_path.write_text("{not-json", encoding="utf-8")
        return 0, "", ""

    result = run_drc_report(
        "drc.json",
        pcb_file=pcb_file,
        output_dir=tmp_path,
        run_cli_variants=run_variants,
        capabilities=SimpleNamespace(
            supports_drc_severity_all=False,
            supports_drc_exit_code_violations=False,
        ),
    )

    assert result.status == "malformed"
    assert result.report is None
    assert result.error is not None
    assert result.error.startswith("DRC report is not valid JSON:")


def test_legacy_tuple_hides_unavailable_and_malformed_reports() -> None:
    path = Path("drc.json")
    clean_report: dict[str, object] = {"violations": [], "unconnected_items": []}

    assert DrcRunResult(path, "clean", clean_report, 0, "", None).as_legacy_tuple() == (
        path,
        clean_report,
        None,
    )
    assert DrcRunResult(path, "malformed", clean_report, 0, "", "bad schema").as_legacy_tuple() == (
        path,
        None,
        "Malformed DRC report: bad schema",
    )


def test_validation_payload_rejects_malformed_report_as_configuration_failure() -> None:
    from kicad_mcp.tools.validation import _drc_report_payload

    payload = _drc_report_payload(
        Path("malformed.json"),
        {"violations": "not-a-list", "unconnected_items": []},
        None,
        save_report=False,
    )

    assert payload.verdict == "FAIL"
    assert payload.summary == "DRC report is malformed."
    assert payload.failure_mode == "configuration"
    assert payload.retryable is False
    assert payload.metadata["report_status"] == "malformed"
    assert "DRC is clean" not in payload.text


def test_validation_and_dfm_wrappers_delegate_to_same_runner(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from kicad_mcp.tools import dfm, validation
    from kicad_mcp.validation import drc_runner

    pcb_file = tmp_path / "board.kicad_pcb"
    pcb_file.write_text("(kicad_pcb)", encoding="utf-8")
    output_dir = tmp_path / "output"
    report = {"violations": [], "unconnected_items": []}
    calls: list[str] = []

    def fake_run(report_name: str, **_kwargs: object) -> DrcRunResult:
        calls.append(report_name)
        return DrcRunResult(output_dir / report_name, "clean", report, 0, "", None)

    monkeypatch.setattr(drc_runner, "run_drc_report", fake_run)
    for module in (validation, dfm):
        monkeypatch.setattr(module, "_get_pcb_file", lambda: pcb_file)
        monkeypatch.setattr(module, "_ensure_output_dir", lambda: output_dir)
        monkeypatch.setattr(
            module, "get_config", lambda: SimpleNamespace(kicad_cli=Path("kicad-cli"))
        )
        monkeypatch.setattr(
            module,
            "get_cli_capabilities",
            lambda _path: SimpleNamespace(
                supports_drc_severity_all=True,
                supports_drc_exit_code_violations=True,
            ),
        )

    assert validation._run_drc_report("validation.json") == (
        output_dir / "validation.json",
        report,
        None,
    )
    assert dfm._run_drc_report("dfm.json") == (
        output_dir / "dfm.json",
        report,
        None,
    )
    assert calls == ["validation.json", "dfm.json"]


def test_dfm_reports_malformed_drc_without_false_pass(monkeypatch) -> None:
    from kicad_mcp.tools import dfm

    monkeypatch.setattr(
        dfm,
        "_run_drc_report",
        lambda _name: (
            Path("dfm.json"),
            {"violations": "not-a-list", "unconnected_items": []},
            None,
        ),
    )
    monkeypatch.setattr(
        dfm,
        "_board_metrics",
        lambda: {
            "copper_layers": 2,
            "min_track_width_mm": 0.2,
            "min_via_drill_mm": 0.3,
            "min_via_diameter_mm": 0.6,
            "via_count": 0,
        },
    )

    lines = dfm._dfm_check_lines(dfm._load_profile("JLCPCB", "standard"))

    assert any("WARN: DRC report malformed" in line for line in lines)
    assert "- PASS: DRC violations: 0" not in lines


def test_architecture_checker_tracks_canonical_drc_runner() -> None:
    from scripts import check_architecture_boundaries as boundaries

    assert "kicad_mcp.validation.drc_runner" in boundaries.DOMAIN_MODULES
    assert "kicad_mcp.validation.drc_runner" in boundaries.PURE_HELPERS
