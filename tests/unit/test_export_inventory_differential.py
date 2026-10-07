from __future__ import annotations

from pathlib import Path

from kicad_mcp.evals.export_inventory_differential import (
    EXPORT_INVENTORY_AUTHORITY,
    EXPORT_INVENTORY_COMPARISON_METHOD,
    EXPORT_INVENTORY_OPERATION,
    classify_export_inventory_differential,
)

SOURCE_SHA = "a" * 40
FIXTURE_HASH = "sha256:" + "b" * 64


def _outputs(tmp_path: Path) -> tuple[Path, Path, Path]:
    gerber_dir = tmp_path / "gerbers"
    drill_dir = tmp_path / "drill"
    gerber_dir.mkdir(parents=True)
    drill_dir.mkdir(parents=True)
    for name in ("demo-F_Cu.gtl", "demo-B_Cu.gbl", "demo-Edge_Cuts.gm1", "demo-job.gbrjob"):
        (gerber_dir / name).write_text(name, encoding="utf-8")
    (drill_dir / "demo.drl").write_text("drill", encoding="utf-8")
    ipc2581 = tmp_path / "board.ipc2581"
    ipc2581.write_text("ipc", encoding="utf-8")
    return gerber_dir, drill_dir, ipc2581


def _classify(tmp_path: Path, **kwargs: object):
    gerber_dir, drill_dir, ipc2581 = _outputs(tmp_path)
    return classify_export_inventory_differential(
        source_sha=SOURCE_SHA,
        lane="stable",
        kicad_version="10.0.6",
        fixture_id="clean-led-kicad10",
        fixture_hash=FIXTURE_HASH,
        gerber_dir=gerber_dir,
        drill_dir=drill_dir,
        ipc2581_path=ipc2581,
        **kwargs,
    )


def test_export_inventory_matches_production_discovery_contract(tmp_path: Path) -> None:
    result = _classify(tmp_path)

    assert result.status == "match"
    assert result.operation == EXPORT_INVENTORY_OPERATION
    assert result.authority == EXPORT_INVENTORY_AUTHORITY
    assert result.comparison_method == EXPORT_INVENTORY_COMPARISON_METHOD
    assert result.native_result_hash == result.custom_result_hash
    assert result.native_pass is None
    assert result.custom_pass is None


def test_seeded_new_native_export_extension_is_detected_as_divergence(tmp_path: Path) -> None:
    gerber_dir, drill_dir, ipc2581 = _outputs(tmp_path)
    (gerber_dir / "demo-future-layer.pho").write_text("future", encoding="utf-8")

    result = classify_export_inventory_differential(
        source_sha=SOURCE_SHA,
        lane="stable",
        kicad_version="10.0.6",
        fixture_id="clean-led-kicad10",
        fixture_hash=FIXTURE_HASH,
        gerber_dir=gerber_dir,
        drill_dir=drill_dir,
        ipc2581_path=ipc2581,
    )

    assert result.status == "divergence"
    assert result.native_result_hash != result.custom_result_hash
    assert result.false_pass is False
    assert result.false_fail is False


def test_failed_native_export_is_unavailable_authority(tmp_path: Path) -> None:
    result = _classify(tmp_path, authority_available=False)

    assert result.status == "unavailable-authority"
    assert result.native_result_hash is None
    assert result.custom_result_hash is None
    assert result.reason == "Native KiCad manufacturing export authority is unavailable."


def test_missing_expected_output_is_infrastructure_invalid(tmp_path: Path) -> None:
    gerber_dir, drill_dir, ipc2581 = _outputs(tmp_path)
    ipc2581.unlink()

    result = classify_export_inventory_differential(
        source_sha=SOURCE_SHA,
        lane="preview",
        kicad_version="11.0.0",
        fixture_id="clean-led-kicad10",
        fixture_hash=FIXTURE_HASH,
        gerber_dir=gerber_dir,
        drill_dir=drill_dir,
        ipc2581_path=ipc2581,
    )

    assert result.status == "infrastructure-invalid"
    assert result.native_result_hash is None
    assert result.custom_result_hash is None
    assert result.reason is not None
    assert "IPC-2581" in result.reason


def test_empty_native_export_directory_is_infrastructure_invalid(tmp_path: Path) -> None:
    gerber_dir, drill_dir, ipc2581 = _outputs(tmp_path)
    for path in gerber_dir.iterdir():
        path.unlink()

    result = classify_export_inventory_differential(
        source_sha=SOURCE_SHA,
        lane="stable",
        kicad_version="10.0.6",
        fixture_id="clean-led-kicad10",
        fixture_hash=FIXTURE_HASH,
        gerber_dir=gerber_dir,
        drill_dir=drill_dir,
        ipc2581_path=ipc2581,
    )

    assert result.status == "infrastructure-invalid"
    assert result.native_result_hash is None
    assert result.custom_result_hash is None
    assert result.reason is not None
    assert "Gerber export produced no files" in result.reason


def test_missing_native_export_directory_is_infrastructure_invalid(tmp_path: Path) -> None:
    gerber_dir, drill_dir, ipc2581 = _outputs(tmp_path)
    for directory, expected in (
        (gerber_dir, "Gerber output directory"),
        (drill_dir, "drill output directory"),
    ):
        for child in directory.iterdir():
            child.unlink()
        directory.rmdir()
        result = classify_export_inventory_differential(
            source_sha=SOURCE_SHA,
            lane="stable",
            kicad_version="10.0.6",
            fixture_id="clean-led-kicad10",
            fixture_hash=FIXTURE_HASH,
            gerber_dir=gerber_dir,
            drill_dir=drill_dir,
            ipc2581_path=ipc2581,
        )
        assert result.status == "infrastructure-invalid"
        assert result.reason is not None
        assert expected in result.reason
        directory.mkdir()
        if directory == gerber_dir:
            (gerber_dir / "demo-F_Cu.gtl").write_text("gerber", encoding="utf-8")
        else:
            (drill_dir / "demo.drl").write_text("drill", encoding="utf-8")


def test_exact_gbr_file_matches_native_inventory_once(tmp_path: Path) -> None:
    gerber_dir, drill_dir, ipc2581 = _outputs(tmp_path)
    (gerber_dir / "legacy.gbr").write_text("legacy", encoding="utf-8")

    result = classify_export_inventory_differential(
        source_sha=SOURCE_SHA,
        lane="stable",
        kicad_version="10.0.6",
        fixture_id="clean-led-kicad10",
        fixture_hash=FIXTURE_HASH,
        gerber_dir=gerber_dir,
        drill_dir=drill_dir,
        ipc2581_path=ipc2581,
    )

    assert result.status == "match"
