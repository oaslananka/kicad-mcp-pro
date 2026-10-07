from __future__ import annotations

from pathlib import Path

import kicad_mcp.evals as evals
from kicad_mcp.evals.live_object_identity_differential import (
    LIVE_OBJECT_IDENTITY_AUTHORITY,
    LIVE_OBJECT_IDENTITY_COMPARISON_METHOD,
    LIVE_OBJECT_IDENTITY_OPERATION,
    classify_live_object_identity_differential,
    hash_live_identity_fixture,
    native_live_object_identity_hash,
)
from kicad_mcp.pcb.live_edit_evidence import LiveBoardIdentity

SOURCE_SHA = "a" * 40


def _fixture(tmp_path: Path) -> tuple[Path, Path]:
    board = tmp_path / "demo.kicad_pcb"
    project = tmp_path / "demo.kicad_pro"
    board.write_text("(kicad_pcb demo)\n", encoding="utf-8")
    project.write_text('{"board": {}}\n', encoding="utf-8")
    return board, project


def _custom_identity(project: Path, board_name: str) -> LiveBoardIdentity:
    native_hash = native_live_object_identity_hash(str(project), board_name)
    return LiveBoardIdentity(
        board_name=board_name,
        internal_key="internal-only",
        fingerprint=native_hash.removeprefix("sha256:"),
    )


def test_live_identity_match_uses_native_and_production_identity_hashes(tmp_path: Path) -> None:
    board, project = _fixture(tmp_path)
    fixture_hash = hash_live_identity_fixture(board)

    result = classify_live_object_identity_differential(
        source_sha=SOURCE_SHA,
        lane="preview",
        kicad_version="11.0.0",
        fixture_id="demo",
        fixture_hash=fixture_hash,
        native_project_path=str(project),
        native_board_name=board.name,
        custom_identity=_custom_identity(project, board.name),
    )

    assert result.status == "match"
    assert result.operation == LIVE_OBJECT_IDENTITY_OPERATION
    assert result.authority == LIVE_OBJECT_IDENTITY_AUTHORITY
    assert result.comparison_method == LIVE_OBJECT_IDENTITY_COMPARISON_METHOD
    assert result.native_result_hash == result.custom_result_hash
    assert str(project) not in result.model_dump_json()


def test_seeded_live_identity_divergence_is_detected(tmp_path: Path) -> None:
    board, project = _fixture(tmp_path)
    fixture_hash = hash_live_identity_fixture(board)
    wrong = LiveBoardIdentity(
        board_name="wrong.kicad_pcb",
        internal_key="internal-only",
        fingerprint="f" * 64,
    )

    result = classify_live_object_identity_differential(
        source_sha=SOURCE_SHA,
        lane="preview",
        kicad_version="11.0.0",
        fixture_id="demo",
        fixture_hash=fixture_hash,
        native_project_path=str(project),
        native_board_name=board.name,
        custom_identity=wrong,
    )

    assert result.status == "divergence"
    assert result.native_result_hash != result.custom_result_hash
    assert result.false_pass is False
    assert result.false_fail is False


def test_live_identity_fails_closed_for_missing_authority(tmp_path: Path) -> None:
    board, _project = _fixture(tmp_path)

    result = classify_live_object_identity_differential(
        source_sha=SOURCE_SHA,
        lane="preview",
        kicad_version="10.99.0",
        fixture_id="demo",
        fixture_hash=hash_live_identity_fixture(board),
        native_project_path=None,
        native_board_name=None,
        custom_identity=None,
        authority_available=False,
        reason="Headless IPC authority is unavailable.",
    )

    assert result.status == "unavailable-authority"
    assert result.native_result_hash is None
    assert result.custom_result_hash is None
    assert result.reason == "Headless IPC authority is unavailable."


def test_live_identity_malformed_native_or_custom_identity_is_infrastructure_invalid(
    tmp_path: Path,
) -> None:
    board, project = _fixture(tmp_path)
    fixture_hash = hash_live_identity_fixture(board)

    malformed_native = classify_live_object_identity_differential(
        source_sha=SOURCE_SHA,
        lane="preview",
        kicad_version="11.0.0",
        fixture_id="demo",
        fixture_hash=fixture_hash,
        native_project_path="",
        native_board_name=board.name,
        custom_identity=_custom_identity(project, board.name),
    )
    malformed_custom = classify_live_object_identity_differential(
        source_sha=SOURCE_SHA,
        lane="preview",
        kicad_version="11.0.0",
        fixture_id="demo",
        fixture_hash=fixture_hash,
        native_project_path=str(project),
        native_board_name=board.name,
        custom_identity=LiveBoardIdentity(
            board_name=board.name,
            internal_key="internal-only",
            fingerprint="not-a-sha256",
        ),
    )

    assert malformed_native.status == "infrastructure-invalid"
    assert malformed_native.reason is not None
    assert "native live identity" in malformed_native.reason.casefold()
    assert malformed_custom.status == "infrastructure-invalid"
    assert malformed_custom.reason is not None
    assert "custom live identity" in malformed_custom.reason.casefold()


def test_live_identity_fixture_hash_covers_board_and_project(tmp_path: Path) -> None:
    board, project = _fixture(tmp_path)
    first = hash_live_identity_fixture(board)

    board.write_text("(kicad_pcb changed)\n", encoding="utf-8")
    second = hash_live_identity_fixture(board)
    project.write_text('{"board": {"changed": true}}\n', encoding="utf-8")
    third = hash_live_identity_fixture(board)

    assert first.startswith("sha256:")
    assert first != second
    assert second != third


def test_eval_package_exports_live_object_identity_surface() -> None:
    assert evals.LIVE_OBJECT_IDENTITY_OPERATION == LIVE_OBJECT_IDENTITY_OPERATION
    assert evals.LIVE_OBJECT_IDENTITY_AUTHORITY == LIVE_OBJECT_IDENTITY_AUTHORITY
    assert evals.LIVE_OBJECT_IDENTITY_COMPARISON_METHOD == LIVE_OBJECT_IDENTITY_COMPARISON_METHOD
    assert (
        evals.classify_live_object_identity_differential
        is classify_live_object_identity_differential
    )
    assert evals.hash_live_identity_fixture is hash_live_identity_fixture
    assert evals.native_live_object_identity_hash is native_live_object_identity_hash
