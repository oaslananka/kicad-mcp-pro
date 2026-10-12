"""Portable cross-project BOM GUI operator fixture is tamper-evident and scoped."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.kicad_107_bom_portable import FixtureError, main, prepare, verify


def test_prepare_and_verify_two_independent_minimal_real_projects(tmp_path: Path) -> None:
    work = tmp_path / "session"
    prepared = prepare(work)
    assert prepared["status"] == "prepared"
    assert prepared["nativeGuiQualified"] is False
    assert prepared["savedNames"][0] != prepared["savedNames"][1]
    assert not (work / "PortableBom107A/PortableBom107A.kicad_pcb").exists()
    report = verify(work)
    assert report["status"] == "integrity-pass"
    assert report["projectSha256Unchanged"] is True
    assert report["nativeGuiQualified"] is False


def test_operator_attestation_never_counts_as_automated_gui_evidence(tmp_path: Path) -> None:
    work = tmp_path / "session"
    names = prepare(work)["savedNames"]
    result = verify(
        work,
        observed_a=names[0],
        observed_b=names[1],
        reopened_b=names[1],
        cancelled_b=True,
    )
    assert result["status"] == "operator-attested"
    assert result["operatorAttested"] is True
    assert result["nativeGuiQualified"] is False


@pytest.mark.parametrize("field", ["observed_a", "observed_b", "reopened_b"])
def test_wrong_operator_observation_is_rejected(tmp_path: Path, field: str) -> None:
    work = tmp_path / "session"
    a, b = prepare(work)["savedNames"]
    options = {"observed_a": a, "observed_b": b, "reopened_b": b, "cancelled_b": True}
    options[field] = "BOM_CROSS_PROJECT_LEAK.csv"
    with pytest.raises(FixtureError, match="operator-"):
        verify(work, **options)


def test_partial_operator_observation_is_rejected(tmp_path: Path) -> None:
    work = tmp_path / "session"
    prepare(work)
    with pytest.raises(FixtureError, match="operator-observation-incomplete"):
        verify(work, cancelled_b=True)


def test_modified_project_json_fails_even_if_saved_filename_is_preserved(tmp_path: Path) -> None:
    work = tmp_path / "session"
    prepare(work)
    p = work / "PortableBom107B/PortableBom107B.kicad_pro"
    p.write_text(p.read_text() + " ")
    with pytest.raises(FixtureError, match="fixture-project-file-changed"):
        verify(work)


def test_modified_schematic_bytes_fail(tmp_path: Path) -> None:
    work = tmp_path / "session"
    prepare(work)
    p = work / "PortableBom107A/PortableBom107A.kicad_sch"
    p.write_text(p.read_text() + " ")
    with pytest.raises(FixtureError, match="fixture-schematic-file-changed"):
        verify(work)


def test_uppercase_bom_extension_is_rejected(tmp_path: Path) -> None:
    work = tmp_path / "session"
    prepare(work)
    (work / "PortableBom107B/WRONG_EXPORT.CSV").write_text("unexpected")
    with pytest.raises(FixtureError, match="fixture-unexpected-bom-output"):
        verify(work)


def test_unexpected_bom_file_is_rejected(tmp_path: Path) -> None:
    work = tmp_path / "session"
    prepare(work)
    (work / "PortableBom107A/BOM.csv").write_text("unexpected")
    with pytest.raises(FixtureError, match="fixture-unexpected-bom-output"):
        verify(work)


def test_existing_workspace_is_never_overwritten(tmp_path: Path) -> None:
    work = tmp_path / "session"
    work.mkdir()
    source = work / "do-not-overwrite.txt"
    source.write_text("keep")
    with pytest.raises(FixtureError, match="workspace-must-be-a-new-absolute-directory"):
        prepare(work)
    assert source.read_text() == "keep"


def test_manifest_hijack_is_rejected(tmp_path: Path) -> None:
    work = tmp_path / "session"
    prepare(work)
    p = work / "manifest.json"
    d = json.loads(p.read_text())
    d["projects"][0]["name"] = "../../private"
    p.write_text(json.dumps(d))
    with pytest.raises(FixtureError, match="fixture-project-name-mismatch"):
        verify(work)


def test_symlinked_project_file_is_never_read(tmp_path: Path) -> None:
    work = tmp_path / "session"
    prepare(work)
    outside = tmp_path / "outside.json"
    outside.write_text('{"secret":"not-for-audit"}')
    p = work / "PortableBom107B/PortableBom107B.kicad_pro"
    p.unlink()
    p.symlink_to(outside)
    with pytest.raises(FixtureError, match="fixture-missing-or-unsafe-file"):
        verify(work)


def test_cli_output_is_bounded_json_and_never_claims_gui_qualification(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    work = tmp_path / "session"
    assert main(["prepare", "--workspace", str(work)]) == 0
    prepared = json.loads(capsys.readouterr().out)
    assert prepared["nativeGuiQualified"] is False
    assert main(["verify", "--workspace", str(work)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "integrity-pass"
    assert report["nativeGuiQualified"] is False
    assert str(tmp_path) not in json.dumps(report)


def test_cli_rejects_partial_attestation_without_printing_workspace_path(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    work = tmp_path / "session"
    prepare(work)
    assert main(["verify", "--workspace", str(work), "--cancelled-b"]) == 2
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "fail"
    assert report["nativeGuiQualified"] is False
    assert str(tmp_path) not in json.dumps(report)
