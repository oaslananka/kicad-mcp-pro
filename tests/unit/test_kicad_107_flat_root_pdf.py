"""KiCad 10.0.7: flat top-level roots must both be present in exported PDF."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

import scripts.kicad_107_flat_root_pdf as probe

ROOT = Path(__file__).resolve().parents[2]


def _reader(*pages: str) -> SimpleNamespace:
    return SimpleNamespace(
        pages=[SimpleNamespace(extract_text=lambda value=text: value) for text in pages]
    )


GOOD_1 = "Size: A4 1/2 Title: erc-power-pin-error File: flat-page1.kicad_sch /FlatRoot1/"
GOOD_2 = "Size: A4 2/2 Title: clean-led-kicad10 File: flat-page2.kicad_sch /FlatRoot2/"


def test_independent_pdf_root_identity_acceptance_any_order() -> None:
    for pages in ((GOOD_1, GOOD_2), (GOOD_2, GOOD_1)):
        report = probe.validate_pdf(_reader(*pages))
        assert report["status"] == "pass"
        assert report["pageCount"] == 2
        assert {page["root"] for page in report["pages"]} == {"FlatRoot1", "FlatRoot2"}
        assert {page["title"] for page in report["pages"]} == {
            "erc-power-pin-error",
            "clean-led-kicad10",
        }
        assert [page["page"] for page in report["pages"]] == [1, 2]


@pytest.mark.parametrize(
    "pages",
    [
        (GOOD_1,),
        (GOOD_1, GOOD_1),
        (GOOD_1, "Missing both identities"),
        (GOOD_1, GOOD_2.replace("clean-led-kicad10", "not-the-correct-title")),
        (GOOD_1 + GOOD_2, ""),
        (GOOD_1, GOOD_2, GOOD_1),
    ],
)
def test_missing_duplicate_or_wrong_root_identity_is_rejected(pages: tuple[str, ...]) -> None:
    reader = _reader(*pages)
    with pytest.raises(probe.ProbeError):
        probe.validate_pdf(reader)


def test_disposable_project_uses_true_kicad_top_level_roots(tmp_path: Path) -> None:
    source = probe.prepare_project(tmp_path / "isolated")
    assert source.name == "flat-page1.kicad_sch"
    project = json.loads(source.with_suffix(".kicad_pro").read_text())
    roots = project["schematic"]["top_level_sheets"]
    assert len(roots) == 2
    assert {e["name"] for e in roots} == {"FlatRoot1", "FlatRoot2"}
    assert len({e["uuid"] for e in roots}) == 2
    assert len({e["filename"] for e in roots}) == 2
    assert project["sheets"] == [[e["uuid"], e["name"]] for e in roots]
    for entry in roots:
        text = (source.parent / entry["filename"]).read_text()
        assert f'(uuid "{entry["uuid"]}")' in text
        assert "(sheet\n" not in text
    assert not (
        ROOT / "packages/kicad-fixtures/fixtures/erc-power-pin-error/flat-page1.kicad_sch"
    ).exists()


def test_version_gate_is_fail_closed_and_no_export_before_check(monkeypatch) -> None:
    def fake_step(cli: Path, step: object, artifacts: Path) -> dict[str, object]:
        assert step.args == ("version",)
        logs = artifacts / "logs"
        logs.mkdir(exist_ok=True)
        (logs / "flat-roots-version.stdout.log").write_text("10.0.6\n")
        return {"ok": True, "returncode": 0}

    monkeypatch.setattr(probe, "_run_step", fake_step)
    with pytest.raises(probe.ProbeError, match="requires KiCad CLI 10.0.7"):
        probe.run_probe("fake-kicad-cli")


def test_audited_runner_executes_version_then_isolated_two_root_pdf(monkeypatch) -> None:
    commands: list[tuple[str, ...]] = []

    def fake_step(cli: Path, step: object, artifacts: Path) -> dict[str, object]:
        commands.append(step.args)
        if step.args == ("version",):
            logs = artifacts / "logs"
            logs.mkdir(exist_ok=True)
            (logs / "flat-roots-version.stdout.log").write_text("10.0.7\n")
            return {"ok": True, "returncode": 0}
        assert step.args[:3] == ("sch", "export", "pdf")
        source = Path(step.args[-1])
        assert source.exists()
        assert source.parent.name == "project"
        Path(step.args[step.args.index("--output") + 1]).write_bytes(b"test-only-stub")
        return {"ok": True, "returncode": 0}

    monkeypatch.setattr(probe, "_run_step", fake_step)
    monkeypatch.setattr(probe, "PdfReader", lambda filename, strict: _reader(GOOD_2, GOOD_1))
    report = probe.run_probe("fake-kicad-cli")
    assert report["status"] == "pass"
    assert report["pageCount"] == 2
    assert len(commands) == 2


def test_workflow_uses_locked_pypdf_and_preserves_gui_manual_boundary() -> None:
    project = (ROOT / "pyproject.toml").read_text()
    assert '"pypdf==6.21.2"' in project
    workflow = yaml.safe_load(
        (ROOT / ".github/workflows/kicad-10-0-7-windows-qualification.yml").read_text()
    )
    events = workflow.get("on", workflow.get(True))
    assert set(events) == {"push", "schedule", "workflow_dispatch"}
    assert events["push"]["branches"] == ["main"]
    assert "scripts/kicad_107_flat_root_pdf.py" in events["push"]["paths"]
    assert workflow["permissions"] == {"contents": "read"}
    steps = workflow["jobs"]["native-windows-cli"]["steps"]
    name = "Verify 10.0.7 flat multi-root schematic PDF pages"
    export_step = next(step for step in steps if step["name"] == name)
    assert "scripts/kicad_107_flat_root_pdf.py" in export_step["run"]
    assert "flat-root-pdf.json" in export_step["run"]
    assert "SOURCE_REVISION" in export_step["env"]
    assert steps.index(export_step) > next(
        i for i, step in enumerate(steps) if step["name"].startswith("Run full native")
    )
    gui = yaml.safe_load(
        (ROOT / ".github/workflows/kicad-10-0-7-windows-gui-ipc-qualification.yml").read_text()
    )
    assert gui.get("on", gui.get(True)) == {"workflow_dispatch": None}
