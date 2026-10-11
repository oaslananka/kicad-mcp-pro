#!/usr/bin/env python3
"""Qualify KiCad 10.0.7 flat *top-level* multi-root schematic PDF plotting.

Upstream #25198: a project with two independent top-level schematic roots
must export both, not just the first one. No GUI, shell, project mutation,
or manufacturing capability is inferred from this bounded native probe.
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from pypdf import PdfReader

try:
    from scripts.kicad_canary import CanaryStep, _resolve_cli, _run_step
    from scripts.runtime_path_safety import approved_runtime_path
except ModuleNotFoundError:  # Direct execution from scripts/.
    from kicad_canary import CanaryStep, _resolve_cli, _run_step
    from runtime_path_safety import approved_runtime_path

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "packages/kicad-fixtures/fixtures"
VERSION = "10.0.7"
ROOTS = (
    ("erc-power-pin-error", "FlatRoot1", "c03d0111-0000-4000-8000-000000000001"),
    ("clean-led-kicad10", "FlatRoot2", "c03d0111-0000-4000-8000-000000000002"),
)


class ProbeError(ValueError):
    """A verified native flat-root PDF export did not meet its acceptance gate."""


def prepare_project(directory: Path) -> Path:
    """Create two independent, uniquely identified roots in a disposable project."""
    directory.mkdir(parents=True, exist_ok=True)
    entries: list[dict[str, str]] = []
    for index, (fixture, name, uuid) in enumerate(ROOTS, 1):
        original = (CORPUS / fixture / f"{fixture}.kicad_sch").read_text(encoding="utf-8")
        marker = '  (paper "A4")'
        if original.count(marker) != 1 or "(sheet\n" in original:
            raise ProbeError("Source is not an independent root schematic fixture")
        if f'(uuid "{uuid}")' in original:
            raise ProbeError("Flat-root UUID collides with the source fixture")
        source = directory / f"flat-page{index}.kicad_sch"
        source.write_text(
            original.replace(marker, f'  (uuid "{uuid}")\n{marker}', 1), encoding="utf-8"
        )
        entries.append({"filename": source.name, "name": name, "uuid": uuid})
    project = {
        "schematic": {"top_level_sheets": entries},
        "sheets": [[entry["uuid"], entry["name"]] for entry in entries],
    }
    (directory / "flat-page1.kicad_pro").write_text(
        json.dumps(project, indent=2) + "\n", encoding="utf-8"
    )
    return directory / "flat-page1.kicad_sch"


def validate_pdf(reader: PdfReader) -> dict[str, Any]:
    """Require both named roots and unique page-title identities, in any order."""
    if len(reader.pages) != len(ROOTS):
        raise ProbeError(f"Expected two independent root PDF pages, got {len(reader.pages)}")
    pages: list[dict[str, Any]] = []
    for index, page in enumerate(reader.pages, 1):
        text = page.extract_text() or ""
        roots = [(fixture, name) for fixture, name, _ in ROOTS if name in text]
        if len(roots) != 1:
            raise ProbeError(f"Ambiguous or missing flat root identity on PDF page {index}")
        fixture, name = roots[0]
        if fixture not in text:
            raise ProbeError(f"Flat root {name} missing its own title {fixture}")
        pages.append({"page": index, "root": name, "title": fixture})
    if {page["root"] for page in pages} != {name for _, name, _ in ROOTS}:
        raise ProbeError("One or more flat top-level root pages were omitted or duplicated")
    return {
        "schemaVersion": "kicad-107-flat-multiroot-pdf.v1",
        "kicadVersion": VERSION,
        "status": "pass",
        "pageCount": len(reader.pages),
        "pages": pages,
    }


def run_probe(cli: str) -> dict[str, Any]:
    """Run pinned native CLI through the existing audited canary subprocess boundary."""
    with tempfile.TemporaryDirectory(prefix="kicad-107-flat-roots-") as temp:
        artifacts = Path(temp)
        version = _run_step(
            Path(cli),
            CanaryStep(name="flat-roots-version", fixture="compatibility", args=("version",)),
            artifacts,
        )
        if not version.get("ok") or version.get("returncode") != 0:
            raise ProbeError("Unable to verify native KiCad 10.0.7 CLI version")
        reported = (artifacts / "logs/flat-roots-version.stdout.log").read_text(encoding="utf-8")
        if reported.strip() != VERSION:
            raise ProbeError("Native flat-root PDF export requires KiCad CLI 10.0.7")
        schematic = prepare_project(artifacts / "project")
        output = artifacts / "flat-roots.pdf"
        result = _run_step(
            Path(cli),
            CanaryStep(
                name="flat-root-pdf-export",
                fixture="flat-multiroot-107",
                args=("sch", "export", "pdf", "--output", str(output), str(schematic)),
                outputs=(output,),
            ),
            artifacts,
        )
        if not result.get("ok") or result.get("returncode") != 0:
            raise ProbeError("Native KiCad 10.0.7 flat-root PDF export failed")
        if not output.is_file() or output.stat().st_size == 0:
            raise ProbeError("Native flat-root PDF export is missing or empty")
        try:
            return validate_pdf(PdfReader(output, strict=True))
        except Exception as exc:
            if isinstance(exc, ProbeError):
                raise
            raise ProbeError("Malformed native flat-root PDF document") from exc


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, help="Source-bound JSON evidence destination")
    args = parser.parse_args()
    result = run_probe(str(_resolve_cli()))
    result["sourceRevision"] = os.environ.get("SOURCE_REVISION", "")
    output = approved_runtime_path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print("KiCad 10.0.7 flat multi-root PDF qualification: 2/2 named top-level pages")


if __name__ == "__main__":
    main()
