"""Prepare and integrity-check two disposable KiCad 10.0.7 BOM GUI projects.

This tool NEVER launches a GUI or claims to have observed its state.
Use a dedicated, interactive native KiCad host for manual observations.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any
from uuid import uuid4

SCHEMA = "kicad-107-bom-portable-operator.v1"
TARGET_KICAD = "10.0.7"
PROJECTS = ("PortableBom107A", "PortableBom107B")
SAVED_NAME = re.compile(r"BOM_SAVED_[AB]_[0-9a-f]{12}\.csv\Z")
CANCELLED_NAME = "BOM_CANCEL_NOT_PERSISTED_107.csv"
MAX_MANIFEST_BYTES = 16384


class FixtureError(Exception):
    """Expected fail-closed, host-path-free error."""


def _digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _schematic(*, document_uuid: str) -> bytes:
    return (
        "(kicad_sch\n"
        " (version 20250114)\n"
        ' (generator "eeschema")\n'
        f' (uuid "{document_uuid}")\n'
        ' (paper "A4")\n'
        " (lib_symbols)\n"
        ' (sheet_instances (path "/" (page "1")))\n'
        " (embedded_fonts no)\n"
        ")\n"
    ).encode()


def _report(*, status: str, project_names: list[str]) -> dict[str, Any]:
    return {
        "schemaVersion": SCHEMA,
        "targetKiCad": TARGET_KICAD,
        "status": status,
        "projectNames": project_names,
        "integrityVerified": status in ("integrity-pass", "operator-attested"),
        "operatorAttested": status == "operator-attested",
        "nativeGuiQualified": False,
    }


def prepare(workspace: Path) -> dict[str, Any]:
    """Create ONLY new named files in a brand-new, operator-specified directory."""
    if not workspace.is_absolute() or workspace.exists():
        raise FixtureError("workspace-must-be-a-new-absolute-directory")
    if not workspace.parent.is_dir() or workspace.parent.is_symlink():
        raise FixtureError("workspace-parent-must-exist-and-not-be-a-symlink")
    workspace.mkdir(mode=0o700)
    records: list[dict[str, str]] = []
    token = uuid4().hex[:12]
    for index, name in enumerate(PROJECTS):
        project_dir = workspace / name
        project_dir.mkdir(mode=0o700)
        saved_name = f"BOM_SAVED_{'AB'[index]}_{token}.csv"
        project_bytes = (
            json.dumps({"schematic": {"bom_export_filename": saved_name}}) + "\n"
        ).encode()
        schematic_bytes = _schematic(document_uuid=str(uuid4()))
        (project_dir / f"{name}.kicad_pro").write_bytes(project_bytes)
        (project_dir / f"{name}.kicad_sch").write_bytes(schematic_bytes)
        records.append(
            {
                "name": name,
                "savedFilename": saved_name,
                "projectSha256": _digest(project_bytes),
                "schematicSha256": _digest(schematic_bytes),
            }
        )
    manifest = {"schemaVersion": SCHEMA, "targetKiCad": TARGET_KICAD, "projects": records}
    (workspace / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return {
        **_report(status="prepared", project_names=list(PROJECTS)),
        "savedNames": [r["savedFilename"] for r in records],
    }


def _read_json(path: Path) -> object:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_MANIFEST_BYTES:
        raise FixtureError("fixture-missing-or-unsafe-file")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, UnicodeError) as exc:
        raise FixtureError("fixture-invalid-json") from exc


def _checked_bytes(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_MANIFEST_BYTES:
        raise FixtureError("fixture-missing-or-unsafe-file")
    return path.read_bytes()


def _read_manifest(workspace: Path) -> list[dict[str, str]]:
    manifest = _read_json(workspace / "manifest.json")
    if not isinstance(manifest, dict) or manifest.get("schemaVersion") != SCHEMA:
        raise FixtureError("fixture-schema-mismatch")
    if manifest.get("targetKiCad") != TARGET_KICAD or not isinstance(
        manifest.get("projects"), list
    ):
        raise FixtureError("fixture-target-mismatch")
    records = manifest["projects"]
    if len(records) != len(PROJECTS):
        raise FixtureError("fixture-project-count-mismatch")
    return records


def _checked_record(workspace: Path, record: object, *, index: int) -> dict[str, str]:
    name = PROJECTS[index]
    if not isinstance(record, dict) or record.get("name") != name:
        raise FixtureError("fixture-project-name-mismatch")
    saved = record.get("savedFilename")
    if (
        not isinstance(saved, str)
        or not SAVED_NAME.fullmatch(saved)
        or f"_{'AB'[index]}_" not in saved
    ):
        raise FixtureError("fixture-saved-filename-invalid")
    project_dir = workspace / name
    if project_dir.is_symlink() or not project_dir.is_dir():
        raise FixtureError("fixture-project-directory-invalid")
    if any(entry.suffix.lower() == ".csv" for entry in project_dir.iterdir()):
        raise FixtureError("fixture-unexpected-bom-output")
    project_bytes = _checked_bytes(project_dir / f"{name}.kicad_pro")
    schematic_bytes = _checked_bytes(project_dir / f"{name}.kicad_sch")
    if _digest(project_bytes) != record.get("projectSha256"):
        raise FixtureError("fixture-project-file-changed")
    if _digest(schematic_bytes) != record.get("schematicSha256"):
        raise FixtureError("fixture-schematic-file-changed")
    project = _read_json(project_dir / f"{name}.kicad_pro")
    if not isinstance(project, dict) or project.get("schematic") != {"bom_export_filename": saved}:
        raise FixtureError("fixture-project-content-changed")
    return {"name": name, "savedFilename": saved}


def verify_integrity(workspace: Path) -> list[dict[str, str]]:
    if workspace.is_symlink() or not workspace.is_dir():
        raise FixtureError("fixture-workspace-is-not-a-directory")
    manifest = _read_manifest(workspace)
    checked = [
        _checked_record(workspace, record, index=index) for index, record in enumerate(manifest)
    ]
    if checked[0]["savedFilename"] == checked[1]["savedFilename"]:
        raise FixtureError("fixture-cross-project-sentinels-identical")
    return checked


def verify(
    workspace: Path,
    *,
    observed_a: str | None = None,
    observed_b: str | None = None,
    reopened_b: str | None = None,
    cancelled_b: bool = False,
) -> dict[str, Any]:
    records = verify_integrity(workspace)
    operator_fields = (observed_a, observed_b, reopened_b)
    operator_supplied = any(v is not None for v in operator_fields) or cancelled_b
    if operator_supplied:
        if not all(v is not None for v in operator_fields) or not cancelled_b:
            raise FixtureError("operator-observation-incomplete")
        if observed_a != records[0]["savedFilename"]:
            raise FixtureError("operator-first-project-output-mismatch")
        if observed_b != records[1]["savedFilename"]:
            raise FixtureError("operator-second-project-output-mismatch")
        if reopened_b != records[1]["savedFilename"]:
            raise FixtureError("operator-cancelled-output-was-retained")
    result = _report(
        status="operator-attested" if operator_supplied else "integrity-pass",
        project_names=list(PROJECTS),
    )
    result["projectSha256Unchanged"] = True
    result["noBomFilesCreated"] = True
    result["savedNames"] = [r["savedFilename"] for r in records]
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="action", required=True)
    create = subcommands.add_parser("prepare", help="Create two new disposable projects")
    create.add_argument("--workspace", type=Path, required=True)
    audit = subcommands.add_parser(
        "verify", help="Check that the prepared project bytes did not change"
    )
    audit.add_argument("--workspace", type=Path, required=True)
    audit.add_argument(
        "--observed-a", default=None, help="Human-observed first project GUI output field"
    )
    audit.add_argument(
        "--observed-b", default=None, help="Human-observed second project GUI output field"
    )
    audit.add_argument(
        "--reopened-b", default=None, help="Human-observed second project field after Cancel"
    )
    audit.add_argument(
        "--cancelled-b", action="store_true", help="Operator attests clicking Cancel, not Export"
    )
    args = parser.parse_args(argv)
    try:
        if args.action == "prepare":
            result = prepare(args.workspace)
        else:
            result = verify(
                args.workspace,
                observed_a=args.observed_a,
                observed_b=args.observed_b,
                reopened_b=args.reopened_b,
                cancelled_b=args.cancelled_b,
            )
    except FixtureError as exc:
        print(
            json.dumps(
                {
                    "schemaVersion": SCHEMA,
                    "status": "fail",
                    "reason": str(exc),
                    "nativeGuiQualified": False,
                }
            )
        )
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
