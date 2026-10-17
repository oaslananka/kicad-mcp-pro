"""Prepare and integrity-check two disposable KiCad 10.0.7 BOM GUI projects.

This tool NEVER launches a GUI or claims to have observed its state.
Use a dedicated, interactive native KiCad host for manual observations.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

SCHEMA = "kicad-107-bom-portable-operator.v1"
TARGET_KICAD = "10.0.7"
PROJECTS = ("PortableBom107A", "PortableBom107B")
SAVED_NAME = re.compile(r"BOM_SAVED_[AB]_[0-9a-f]{12}\.csv\Z")
CANCELLED_NAME = "BOM_CANCEL_NOT_PERSISTED_107.csv"
MAX_MANIFEST_BYTES = 16384
MANIFEST_FILENAME = "manifest.json"
# KiCad 10.0.7 expands a minimal .kicad_pro on first GUI close.
NORMALIZED_PROJECT_KEYS = frozenset(
    {
        "board",
        "boards",
        "component_class_settings",
        "cvpcb",
        "erc",
        "libraries",
        "meta",
        "net_settings",
        "pcbnew",
        "schematic",
        "sheets",
        "text_variables",
        "tuning_profiles",
    }
)


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


def _session_workspace(session: str) -> Path:
    """Map a strictly bounded opaque session token to the OS temporary root."""
    if not re.fullmatch(r"[0-9a-f]{32}", session):
        raise FixtureError("session-identifier-invalid")
    return Path(tempfile.gettempdir()) / f"kicad-107-bom-operator-{session}"


def prepare() -> dict[str, Any]:
    """Only create a fresh random session below the OS-managed temp root."""
    session = uuid4().hex
    workspace = _session_workspace(session)
    try:
        workspace.mkdir(mode=0o700)
    except FileExistsError as exc:
        raise FixtureError("workspace-session-already-exists") from exc
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
    (workspace / MANIFEST_FILENAME).write_text(json.dumps(manifest, indent=2) + "\n")
    return {
        **_report(status="prepared", project_names=list(PROJECTS)),
        "savedNames": [r["savedFilename"] for r in records],
        "sessionId": session,
    }


def _read_json(path: Path) -> object:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_MANIFEST_BYTES:
        raise FixtureError("fixture-missing-or-unsafe-file")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise FixtureError("fixture-invalid-json") from exc


def _checked_bytes(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_MANIFEST_BYTES:
        raise FixtureError("fixture-missing-or-unsafe-file")
    return path.read_bytes()


def _read_manifest(workspace: Path) -> list[dict[str, str]]:
    manifest = _read_json(workspace / MANIFEST_FILENAME)
    if not isinstance(manifest, dict) or manifest.get("schemaVersion") != SCHEMA:
        raise FixtureError("fixture-schema-mismatch")
    if manifest.get("targetKiCad") != TARGET_KICAD or not isinstance(
        manifest.get("projects"), list
    ):
        raise FixtureError("fixture-target-mismatch")
    records = manifest["projects"]
    if len(records) != len(PROJECTS):
        raise FixtureError("fixture-project-count-mismatch")
    return cast(list[dict[str, str]], records)


def _record_header(record: object, index: int) -> tuple[dict[str, Any], str]:
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
    return cast(dict[str, Any], record), saved


def _checked_record(workspace: Path, record: object, *, index: int) -> dict[str, str]:
    record, saved = _record_header(record, index)
    name = PROJECTS[index]
    project_dir = workspace / name
    if project_dir.is_symlink() or not project_dir.is_dir():
        raise FixtureError("fixture-project-directory-invalid")
    if any(entry.suffix.lower() == ".csv" for entry in project_dir.iterdir()):
        raise FixtureError("fixture-unexpected-bom-output")
    project_bytes = _checked_bytes(project_dir / f"{name}.kicad_pro")
    schematic_bytes = _checked_bytes(project_dir / f"{name}.kicad_sch")
    baseline_sha = record.get("baselineProjectSha256")
    if baseline_sha is not None and (
        not isinstance(baseline_sha, str) or not re.fullmatch(r"[0-9a-f]{64}", baseline_sha)
    ):
        raise FixtureError("fixture-baseline-invalid")
    expected_sha = baseline_sha if baseline_sha is not None else record.get("projectSha256")
    if _digest(project_bytes) != expected_sha:
        raise FixtureError("fixture-project-file-changed")
    if _digest(schematic_bytes) != record.get("schematicSha256"):
        raise FixtureError("fixture-schematic-file-changed")
    project = _read_json(project_dir / f"{name}.kicad_pro")
    if not isinstance(project, dict):
        raise FixtureError("fixture-project-content-changed")
    if baseline_sha is None:
        if project.get("schematic") != {"bom_export_filename": saved}:
            raise FixtureError("fixture-project-content-changed")
    else:
        _check_normalized_project(project, saved)
    return {"name": name, "savedFilename": saved}


def _check_normalized_project(project: dict[str, Any], saved: str) -> None:
    """Allow *only* known native KiCad 10.0.7 top-level default settings."""
    required = {"board", "boards", "meta", "pcbnew", "schematic"}
    if not required.issubset(project) or not set(project).issubset(NORMALIZED_PROJECT_KEYS):
        raise FixtureError("fixture-project-normalization-unexpected")
    if any(not isinstance(project[key], dict) for key in required - {"boards"}):
        raise FixtureError("fixture-project-normalization-unexpected")
    if not isinstance(project["boards"], list):
        raise FixtureError("fixture-project-normalization-unexpected")
    if project["schematic"].get("bom_export_filename") != saved:
        raise FixtureError("fixture-project-content-changed")


def _baseline_digest(workspace: Path, record: object, index: int) -> str:
    record, saved = _record_header(record, index)
    if record.get("baselineProjectSha256") is not None:
        raise FixtureError("fixture-baseline-already-armed")
    project_name = PROJECTS[index]
    project_dir = workspace / project_name
    if project_dir.is_symlink() or not project_dir.is_dir():
        raise FixtureError("fixture-project-directory-invalid")
    if any(x.suffix.lower() == ".csv" for x in project_dir.iterdir()):
        raise FixtureError("fixture-unexpected-bom-output")
    schematic = _checked_bytes(project_dir / f"{project_name}.kicad_sch")
    if _digest(schematic) != record.get("schematicSha256"):
        raise FixtureError("fixture-schematic-file-changed")
    project_path = project_dir / f"{project_name}.kicad_pro"
    project_bytes = _checked_bytes(project_path)
    if _digest(project_bytes) == record.get("projectSha256"):
        raise FixtureError("fixture-project-not-initialized")
    project = _read_json(project_path)
    if not isinstance(project, dict):
        raise FixtureError("fixture-project-normalization-unexpected")
    _check_normalized_project(project, saved)
    return _digest(project_bytes)


def arm_baseline(workspace: Path) -> dict[str, Any]:
    """Seal native one-time initialization *before* the actual BOM GUI test.

    Explicit operator step.  Never automatically accept changed project bytes
    during post-test verification, and never claim this attests a GUI run.
    """
    if workspace.is_symlink() or not workspace.is_dir():
        raise FixtureError("fixture-workspace-is-not-a-directory")
    records = _read_manifest(workspace)
    manifest_path = workspace / MANIFEST_FILENAME
    raw_manifest = _read_json(manifest_path)
    if not isinstance(raw_manifest, dict):
        raise FixtureError("fixture-baseline-already-armed")
    manifest: dict[str, Any] = cast(dict[str, Any], raw_manifest)
    if manifest.get("baselineState") is not None:
        raise FixtureError("fixture-baseline-already-armed")
    sealed = [_baseline_digest(workspace, record, index) for index, record in enumerate(records)]
    if records[0]["savedFilename"] == records[1]["savedFilename"]:
        raise FixtureError("fixture-cross-project-sentinels-identical")
    for record, digest in zip(manifest["projects"], sealed, strict=True):
        record["baselineProjectSha256"] = digest
    manifest["baselineState"] = "armed"
    # Prevent partially written manifests; stay in the same bounded workspace.
    replacement = workspace / "manifest.json.pending"
    if replacement.exists() or replacement.is_symlink():
        raise FixtureError("fixture-baseline-pending-file-exists")
    try:
        replacement.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        os.replace(replacement, manifest_path)
    finally:
        replacement.unlink(missing_ok=True)
    result = _report(status="baseline-armed", project_names=list(PROJECTS))
    result["projectNormalizationObserved"] = True
    result["nativeGuiQualified"] = False
    return result


def verify_integrity(workspace: Path) -> list[dict[str, str]]:
    if workspace.is_symlink() or not workspace.is_dir():
        raise FixtureError("fixture-workspace-is-not-a-directory")
    manifest = _read_manifest(workspace)
    marker = _read_json(workspace / MANIFEST_FILENAME)
    if not isinstance(marker, dict):
        raise FixtureError("fixture-invalid-manifest")
    armed = marker.get("baselineState") == "armed"
    if marker.get("baselineState") not in (None, "armed"):
        raise FixtureError("fixture-baseline-invalid")
    if any(("baselineProjectSha256" in record) != armed for record in manifest):
        raise FixtureError("fixture-baseline-invalid")
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
    marker = _read_json(workspace / MANIFEST_FILENAME)
    armed = isinstance(marker, dict) and marker.get("baselineState") == "armed"
    # The prepared files may have been expanded by KiCad *before* baseline.
    result["projectSha256Unchanged"] = not armed
    result["projectSha256UnchangedSinceBaseline"] = True
    result["projectNormalizationObserved"] = armed
    result["noBomFilesCreated"] = True
    result["savedNames"] = [r["savedFilename"] for r in records]
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="action", required=True)
    subcommands.add_parser("prepare", help="Create a secure random OS-temp session")
    for action in ("verify", "locate", "baseline"):
        subcommands.add_parser(action).add_argument("--session", required=True)
    # Only the integrity-check subcommand accepts optional GUI observations.
    audit = subcommands.choices["verify"]
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
            result = prepare()
        else:
            workspace = _session_workspace(args.session)
            if args.action == "baseline":
                result = arm_baseline(workspace)
            elif args.action == "locate":
                verify_integrity(workspace)
                # Local, explicitly requested operator output only; not in JSON evidence.
                print(workspace)
                return 0
            else:
                result = verify(
                    workspace,
                    observed_a=args.observed_a,
                    observed_b=args.observed_b,
                    reopened_b=args.reopened_b,
                    cancelled_b=args.cancelled_b,
                )
    except (FixtureError, OSError) as exc:
        reason = (
            str(exc) if isinstance(exc, FixtureError) else "fixture-filesystem-operation-failed"
        )
        print(
            json.dumps(
                {
                    "schemaVersion": SCHEMA,
                    "status": "fail",
                    "reason": reason,
                    "nativeGuiQualified": False,
                }
            )
        )
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
