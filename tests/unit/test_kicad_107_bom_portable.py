"""Portable KiCad BOM operator sessions are fail-closed and path-safe."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

import pytest

import scripts.kicad_107_bom_portable as tool


@pytest.fixture
def session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, dict]:
    monkeypatch.setattr(tool.tempfile, "gettempdir", lambda: str(tmp_path))
    report = tool.prepare()
    return tool._session_workspace(report["sessionId"]), report


def test_generate_two_unique_os_temp_schematics(session: tuple[Path, dict]) -> None:
    work, prepared = session
    assert prepared["status"] == "prepared"
    assert prepared["nativeGuiQualified"] is False
    assert len(prepared["sessionId"]) == 32
    assert prepared["savedNames"][0] != prepared["savedNames"][1]
    assert work.parent.is_dir()
    assert not (work / "PortableBom107A/PortableBom107A.kicad_pcb").exists()
    result = tool.verify(work)
    assert result["status"] == "integrity-pass"
    assert result["projectSha256Unchanged"] is True
    assert result["nativeGuiQualified"] is False


def test_operator_attestation_never_counts_as_automatic_gui_evidence(
    session: tuple[Path, dict],
) -> None:
    work, data = session
    a, b = data["savedNames"]
    result = tool.verify(work, observed_a=a, observed_b=b, reopened_b=b, cancelled_b=True)
    assert result["status"] == "operator-attested"
    assert result["operatorAttested"] is True
    assert result["nativeGuiQualified"] is False


@pytest.mark.parametrize("field", ["observed_a", "observed_b", "reopened_b"])
def test_wrong_operator_observation_fails(session: tuple[Path, dict], field: str) -> None:
    work, data = session
    a, b = data["savedNames"]
    options = {"observed_a": a, "observed_b": b, "reopened_b": b, "cancelled_b": True}
    options[field] = "BOM_STALE_CROSS_PROJECT_LEAK.csv"
    with pytest.raises(tool.FixtureError, match="operator-"):
        tool.verify(work, **options)


def test_partial_operator_attestation_fails(session: tuple[Path, dict]) -> None:
    with pytest.raises(tool.FixtureError, match="operator-observation-incomplete"):
        tool.verify(session[0], cancelled_b=True)


@pytest.mark.parametrize("filename", ["PortableBom107A.kicad_sch", "PortableBom107B.kicad_pro"])
def test_file_modification_fails(session: tuple[Path, dict], filename: str) -> None:
    work = session[0]
    name = filename.split(".")[0]
    file = work / name / filename
    file.write_text(file.read_text() + " ")
    with pytest.raises(tool.FixtureError, match="fixture-(project|schematic)-file-changed"):
        tool.verify(work)


@pytest.mark.parametrize("extension", ["csv", "CSV"])
def test_unexpected_bom_file_fails(session: tuple[Path, dict], extension: str) -> None:
    work = session[0]
    (work / "PortableBom107A" / f"UNEXPECTED.{extension}").write_text("unexpected")
    with pytest.raises(tool.FixtureError, match="fixture-unexpected-bom-output"):
        tool.verify(work)


def _simulate_native_project_initialization(session: tuple[Path, dict]) -> None:
    work, data = session
    for name, saved in zip(tool.PROJECTS, data["savedNames"], strict=True):
        file = work / name / f"{name}.kicad_pro"
        # Reflect the stable KiCad 10.0.7 full-project shape from the Windows run.
        normalized = {
            "board": {},
            "boards": [],
            "component_class_settings": {},
            "cvpcb": {},
            "erc": {},
            "libraries": {},
            "meta": {},
            "net_settings": {},
            "pcbnew": {},
            "schematic": {"bom_export_filename": saved},
            "sheets": {},
            "text_variables": {},
            "tuning_profiles": {},
        }
        file.write_text(json.dumps(normalized))


def test_baseline_requires_native_initialization(session: tuple[Path, dict]) -> None:
    with pytest.raises(tool.FixtureError, match="fixture-project-not-initialized"):
        tool.arm_baseline(session[0])
    assert tool.verify(session[0])["status"] == "integrity-pass"


def test_native_initialization_can_be_sealed_before_gui_observation(
    session: tuple[Path, dict],
) -> None:
    work, prepared = session
    _simulate_native_project_initialization(session)
    with pytest.raises(tool.FixtureError, match="fixture-project-file-changed"):
        tool.verify(work)
    result = tool.arm_baseline(work)
    assert result["status"] == "baseline-armed"
    assert result["nativeGuiQualified"] is False
    with pytest.raises(tool.FixtureError, match="fixture-baseline-already-armed"):
        tool.arm_baseline(work)
    a, b = prepared["savedNames"]
    verified = tool.verify(work, observed_a=a, observed_b=b, reopened_b=b, cancelled_b=True)
    assert verified["status"] == "operator-attested"
    assert verified["projectSha256Unchanged"] is False
    assert verified["projectSha256UnchangedSinceBaseline"] is True
    assert verified["projectNormalizationObserved"] is True
    assert verified["nativeGuiQualified"] is False


def test_project_changes_after_baseline_are_still_rejected(
    session: tuple[Path, dict],
) -> None:
    work = session[0]
    _simulate_native_project_initialization(session)
    tool.arm_baseline(work)
    file = work / "PortableBom107A" / "PortableBom107A.kicad_pro"
    data = json.loads(file.read_text())
    data["board"]["settings"] = "unexpected-edit"
    file.write_text(json.dumps(data))
    with pytest.raises(tool.FixtureError, match="fixture-project-file-changed"):
        tool.verify(work)


@pytest.mark.parametrize("mutation", ["bom", "unknown-key", "schematic", "csv"])
def test_baseline_rejects_unexpected_initializer_changes(
    session: tuple[Path, dict], mutation: str
) -> None:
    work = session[0]
    _simulate_native_project_initialization(session)
    project = work / "PortableBom107B/PortableBom107B.kicad_pro"
    data = json.loads(project.read_text())
    if mutation == "bom":
        data["schematic"]["bom_export_filename"] = tool.CANCELLED_NAME
    elif mutation == "unknown-key":
        data["arbitrary_private_settings"] = {"foo": "bar"}
    elif mutation == "schematic":
        schematic = work / "PortableBom107B/PortableBom107B.kicad_sch"
        schematic.write_text(schematic.read_text() + " ")
    elif mutation == "csv":
        (work / "PortableBom107B/unexpected.csv").write_text("data")
    project.write_text(json.dumps(data))
    with pytest.raises(tool.FixtureError, match="fixture-"):
        tool.arm_baseline(work)


def test_cli_baseline_command_is_explicit_and_path_free(
    session: tuple[Path, dict], capsys: pytest.CaptureFixture[str]
) -> None:
    work, prepared = session
    _simulate_native_project_initialization(session)
    assert tool.main(["baseline", "--session", prepared["sessionId"]]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "baseline-armed"
    assert report["nativeGuiQualified"] is False
    assert str(work) not in json.dumps(report)
    assert tool.main(["verify", "--session", prepared["sessionId"]]) == 0
    verified = json.loads(capsys.readouterr().out)
    assert verified["projectNormalizationObserved"] is True


def test_existing_session_is_never_overwritten(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tool.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(tool, "uuid4", lambda: UUID("f31c783b-08e9-4d4e-99da-535b9f36fada"))
    path = tool._session_workspace("f31c783b08e94d4e99da535b9f36fada")
    path.mkdir()
    (path / "keep.txt").write_text("do not overwrite")
    with pytest.raises(tool.FixtureError, match="workspace-session-already-exists"):
        tool.prepare()
    assert (path / "keep.txt").read_text() == "do not overwrite"


def test_manifest_traversal_is_rejected(session: tuple[Path, dict]) -> None:
    work = session[0]
    file = work / "manifest.json"
    obj = json.loads(file.read_text())
    obj["projects"][0]["name"] = "../../private"
    file.write_text(json.dumps(obj))
    with pytest.raises(tool.FixtureError, match="fixture-project-name-mismatch"):
        tool.verify(work)


def test_symlinked_project_is_rejected(session: tuple[Path, dict], tmp_path: Path) -> None:
    work = session[0]
    outside = tmp_path / "private-file"
    outside.write_text("secret")
    project = work / "PortableBom107B/PortableBom107B.kicad_pro"
    project.unlink()
    try:
        project.symlink_to(outside)
    except OSError as exc:
        if getattr(exc, "winerror", None) == 1314:
            pytest.skip("Windows host forbids unprivileged symlink creation")
        raise
    with pytest.raises(tool.FixtureError, match="fixture-missing-or-unsafe-file"):
        tool.verify(work)


@pytest.mark.parametrize(
    "untrusted", ["../../etc/passwd", "C:\\Windows", "prefix/anything", "bad-token", "A" * 32]
)
def test_cli_session_input_cannot_escape_system_temp(untrusted: str) -> None:
    with pytest.raises(tool.FixtureError, match="session-identifier-invalid"):
        tool._session_workspace(untrusted)


def test_cli_uses_opaque_session_not_operator_supplied_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(tool.tempfile, "gettempdir", lambda: str(tmp_path))
    assert tool.main(["prepare"]) == 0
    prepared = json.loads(capsys.readouterr().out)
    assert prepared["nativeGuiQualified"] is False
    token = prepared["sessionId"]
    assert tool.main(["verify", "--session", token]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "integrity-pass"
    assert report["nativeGuiQualified"] is False
    assert str(tmp_path) not in json.dumps(report)
    assert tool.main(["locate", "--session", token]) == 0
    assert capsys.readouterr().out.strip() == str(tool._session_workspace(token))


def test_cli_rejects_bad_session_without_leaking_host_path(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    assert tool.main(["verify", "--session", str(tmp_path)]) == 2
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "fail"
    assert report["reason"] == "session-identifier-invalid"
    assert str(tmp_path) not in json.dumps(report)
