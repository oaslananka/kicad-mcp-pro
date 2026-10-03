from __future__ import annotations

import importlib
import importlib.util
import json
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType

import pytest


def _module() -> ModuleType:
    spec = importlib.util.find_spec("kicad_mcp.manufacturing.release_manifest")
    assert spec is not None, "Manufacturing release-manifest service must be extracted"
    return importlib.import_module("kicad_mcp.manufacturing.release_manifest")


class FakeIntent:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def model_dump(self) -> dict[str, object]:
        return self.payload


def _context(tmp_path: Path):  # type: ignore[no-untyped-def]
    module = _module()
    project = tmp_path / "demo.kicad_pro"
    pcb = tmp_path / "demo.kicad_pcb"
    sch = tmp_path / "demo.kicad_sch"
    for path, text in ((project, "project"), (pcb, "pcb"), (sch, "sch")):
        path.write_text(text, encoding="utf-8")
    return module.ReleaseManifestContext(
        output_dir=tmp_path / "output",
        project_file=project,
        pcb_file=pcb,
        sch_file=sch,
        kicad_cli=Path("/usr/bin/kicad-cli"),
        kicad_cli_version="10.0.6",
        kicad_mcp_version="3.37.0",
    )


def test_release_manifest_requires_existing_release_files(tmp_path: Path) -> None:
    module = _module()
    context = _context(tmp_path)
    service = module.ReleaseManifestService()
    empty_intent = FakeIntent({})

    with pytest.raises(
        module.ReleaseManifestPrerequisiteError,
        match="Output directory does not exist",
    ):
        service.create_manifest(intent=empty_intent, context=context)

    context.output_dir.mkdir()
    with pytest.raises(
        module.ReleaseManifestPrerequisiteError,
        match="No release files found in output directory",
    ):
        service.create_manifest(intent=empty_intent, context=context)


def test_release_manifest_persists_deterministic_hash_and_provenance(tmp_path: Path) -> None:
    module = _module()
    context = _context(tmp_path)
    context.output_dir.mkdir()
    (context.output_dir / "demo.drl").write_text("drill", encoding="utf-8")
    (context.output_dir / "demo-F_Cu.gbr").write_text("gerber", encoding="utf-8")
    intent = FakeIntent({"board": "demo", "revision": 2})

    first = module.ReleaseManifestService(
        now_utc=lambda: datetime(2026, 10, 3, 1, 2, tzinfo=UTC)
    ).create_manifest(intent=intent, context=context, output_path="ignored")
    first_payload = json.loads((context.output_dir / "manifest.json").read_text(encoding="utf-8"))
    second = module.ReleaseManifestService(
        now_utc=lambda: datetime(2026, 10, 3, 2, 3, tzinfo=UTC)
    ).create_manifest(intent=intent, context=context, output_path="still-ignored")
    second_payload = json.loads((context.output_dir / "manifest.json").read_text(encoding="utf-8"))

    assert "Release manifest generated:" in first
    assert "Release manifest generated:" in second
    assert first_payload["content_hash"] == second_payload["content_hash"]
    assert first_payload["generated_utc"] != second_payload["generated_utc"]
    assert first_payload["provenance"] == {
        "kicad_mcp_version": "3.37.0",
        "kicad_cli": str(context.kicad_cli),
        "kicad_cli_version": "10.0.6",
        "intent_hash": first_payload["intent_hash"],
        "source_hashes": {
            "project": first_payload["provenance"]["source_hashes"]["project"],
            "pcb": first_payload["provenance"]["source_hashes"]["pcb"],
            "schematic": first_payload["provenance"]["source_hashes"]["schematic"],
        },
    }
    assert [entry["filename"] for entry in first_payload["files"]] == [
        "demo-F_Cu.gbr",
        "demo.drl",
    ]
    manifest_text = (context.output_dir / "MANIFEST.txt").read_text(encoding="utf-8")
    assert "kicad-mcp-pro Release Manifest" in manifest_text
    assert f"Content hash: {second_payload['content_hash']}" in manifest_text
    assert "demo-F_Cu.gbr" in manifest_text
    assert "demo.drl" in manifest_text
