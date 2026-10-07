"""Native headless-IPC live-board identity semantic differential helpers."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from ..pcb.live_edit_evidence import LiveBoardIdentity
from .semantic_differential import (
    DifferentialLane,
    DifferentialResult,
    classify_differential_result,
)

LIVE_OBJECT_IDENTITY_AUTHORITY = "kicad-headless-ipc:board-project-identity"
LIVE_OBJECT_IDENTITY_OPERATION = "live-object.board-identity"
LIVE_OBJECT_IDENTITY_COMPARISON_METHOD = "resolved-project-path-board-name-sha256.v1"
_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")
_FIXTURE_SUFFIXES = frozenset({".kicad_pcb", ".kicad_pro"})


def _identity_material(project_path: str, board_name: str) -> bytes:
    raw_path = str(project_path).strip()
    name = str(board_name).strip()
    if not raw_path or not name:
        raise ValueError("Native live identity requires project path and board name")
    normalized_path = str(Path(raw_path).expanduser().resolve(strict=False))
    return f"{normalized_path}\0{name}".encode()


def native_live_object_identity_hash(project_path: str, board_name: str) -> str:
    """Hash native KiCad board/project identity without exposing the project path."""
    return f"sha256:{hashlib.sha256(_identity_material(project_path, board_name)).hexdigest()}"


def _custom_identity_hash(identity: LiveBoardIdentity) -> str:
    if not identity.board_name.strip() or not _SHA256_HEX.fullmatch(identity.fingerprint):
        raise ValueError("Custom live identity requires a board name and SHA-256 fingerprint")
    return f"sha256:{identity.fingerprint}"


def hash_live_identity_fixture(project_or_board: Path) -> str:
    """Hash the paired board/project files used by the headless identity probe."""
    resolved = project_or_board.expanduser().resolve(strict=True)
    if resolved.suffix not in _FIXTURE_SUFFIXES:
        raise ValueError(f"Unsupported live identity fixture: {project_or_board}")
    board = resolved if resolved.suffix == ".kicad_pcb" else resolved.with_suffix(".kicad_pcb")
    project = resolved if resolved.suffix == ".kicad_pro" else resolved.with_suffix(".kicad_pro")
    files = (board, project)
    if any(not path.is_file() for path in files):
        raise ValueError("Live identity fixture requires paired .kicad_pcb and .kicad_pro files")

    digest = hashlib.sha256()
    for path in files:
        name = path.name.encode("utf-8")
        content = path.read_bytes()
        digest.update(len(name).to_bytes(8, "big"))
        digest.update(name)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return f"sha256:{digest.hexdigest()}"


def classify_live_object_identity_differential(
    *,
    source_sha: str,
    lane: DifferentialLane,
    kicad_version: str,
    fixture_id: str,
    fixture_hash: str,
    native_project_path: str | None,
    native_board_name: str | None,
    custom_identity: LiveBoardIdentity | None,
    authority_available: bool = True,
    infrastructure_valid: bool = True,
    reason: str | None = None,
) -> DifferentialResult:
    """Compare raw native board identity with MCP Pro's production live identity mapping."""

    def classify(
        *,
        native_result_hash: str | None,
        custom_result_hash: str | None,
        authority_available_value: bool = True,
        infrastructure_valid_value: bool = True,
        result_reason: str | None = None,
    ) -> DifferentialResult:
        return classify_differential_result(
            source_sha=source_sha,
            lane=lane,
            kicad_version=kicad_version,
            fixture_id=fixture_id,
            fixture_hash=fixture_hash,
            operation=LIVE_OBJECT_IDENTITY_OPERATION,
            authority=LIVE_OBJECT_IDENTITY_AUTHORITY,
            comparison_method=LIVE_OBJECT_IDENTITY_COMPARISON_METHOD,
            native_result_hash=native_result_hash,
            custom_result_hash=custom_result_hash,
            authority_available=authority_available_value,
            infrastructure_valid=infrastructure_valid_value,
            reason=result_reason,
        )

    if not infrastructure_valid:
        return classify(
            native_result_hash=None,
            custom_result_hash=None,
            infrastructure_valid_value=False,
            result_reason=reason or "Live object identity differential infrastructure is invalid.",
        )
    if not authority_available:
        return classify(
            native_result_hash=None,
            custom_result_hash=None,
            authority_available_value=False,
            result_reason=reason or "KiCad headless IPC live identity authority is unavailable.",
        )

    try:
        if native_project_path is None or native_board_name is None:
            raise ValueError("missing project path or board name")
        native_hash = native_live_object_identity_hash(native_project_path, native_board_name)
    except (OSError, ValueError) as exc:
        return classify(
            native_result_hash=None,
            custom_result_hash=None,
            infrastructure_valid_value=False,
            result_reason=f"Native live identity is invalid: {exc}",
        )

    try:
        if custom_identity is None:
            raise ValueError("production live identity was not produced")
        custom_hash = _custom_identity_hash(custom_identity)
    except ValueError as exc:
        return classify(
            native_result_hash=None,
            custom_result_hash=None,
            infrastructure_valid_value=False,
            result_reason=f"Custom live identity is invalid: {exc}",
        )

    return classify(
        native_result_hash=native_hash,
        custom_result_hash=custom_hash,
    )


__all__ = [
    "LIVE_OBJECT_IDENTITY_AUTHORITY",
    "LIVE_OBJECT_IDENTITY_COMPARISON_METHOD",
    "LIVE_OBJECT_IDENTITY_OPERATION",
    "classify_live_object_identity_differential",
    "hash_live_identity_fixture",
    "native_live_object_identity_hash",
]
