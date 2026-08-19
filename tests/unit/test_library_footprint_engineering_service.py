from __future__ import annotations

import importlib
import importlib.util
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType


def _module() -> ModuleType:
    spec = importlib.util.find_spec("kicad_mcp.library.footprint_engineering")
    assert spec is not None, "Footprint engineering service must be extracted"
    return importlib.import_module("kicad_mcp.library.footprint_engineering")


@dataclass(frozen=True)
class UpgradeResult:
    upgraded: bool
    detail: str


def _service(
    tmp_path: Path,
    *,
    upgraded: bool = True,
    resolve_error: Exception | None = None,
):
    module = _module()
    upgrades: list[Path] = []

    def resolve(relative: str) -> Path:
        if resolve_error is not None:
            raise resolve_error
        return tmp_path / relative

    def upgrade(path: Path) -> UpgradeResult:
        upgrades.append(path)
        return UpgradeResult(upgraded=upgraded, detail="cli unavailable")

    service = module.LibraryFootprintEngineeringService(
        resolve_within_project=resolve,
        default_output_dir=lambda: tmp_path / "output",
        upgrade_generated_footprint=upgrade,
    )
    return service, upgrades


def test_generate_footprint_preserves_custom_path_and_migration_note(tmp_path: Path) -> None:
    service, upgrades = _service(tmp_path, upgraded=False)

    result = service.generate_footprint_ipc7351("0805", output_path="custom/R_0805.kicad_mod")

    path = tmp_path / "custom" / "R_0805.kicad_mod"
    assert path.exists()
    assert path.read_text(encoding="utf-8").startswith("(footprint")
    assert upgrades == [path]
    assert result.startswith(f"Footprint saved to {path}\nPackage: 0805, Density: B")
    assert "Format note: kept repository writer dialect" in result
    assert "cli unavailable" in result


def test_generate_footprint_preserves_default_output_location(tmp_path: Path) -> None:
    service, upgrades = _service(tmp_path)

    result = service.generate_footprint_ipc7351("0805")

    path = tmp_path / "output" / "footprints" / "0805.kicad_mod"
    assert path.exists()
    assert upgrades == [path]
    assert result.startswith(f"Footprint saved to {path}")
    assert "Format note:" not in result


def test_generate_footprint_rejects_invalid_density_before_writing(tmp_path: Path) -> None:
    service, upgrades = _service(tmp_path)

    result = service.generate_footprint_ipc7351("0805", density="Z")

    assert result == "Invalid density 'Z'. Must be A, B, or C."
    assert upgrades == []
    assert not (tmp_path / "output").exists()


def test_validate_footprint_preserves_path_safety_error(tmp_path: Path) -> None:
    service, _ = _service(tmp_path, resolve_error=ValueError("outside project"))

    result = service.validate_footprint_ipc7351("../unsafe.kicad_mod", "0805")

    assert result == "Invalid footprint path: outside project"


def test_validate_footprint_reports_missing_file(tmp_path: Path) -> None:
    service, _ = _service(tmp_path)

    result = service.validate_footprint_ipc7351("missing.kicad_mod", "0805")

    assert result == f"Footprint file not found: {tmp_path / 'missing.kicad_mod'}"


def test_generate_validate_and_certify_round_trip(tmp_path: Path) -> None:
    service, _ = _service(tmp_path)
    relative = "generated/0805.kicad_mod"

    generated = service.generate_footprint_ipc7351("0805", output_path=relative)
    validated = service.validate_footprint_ipc7351(relative, "0805")
    certified = service.certify_footprint(relative)

    assert generated.startswith("Footprint saved to")
    assert validated.startswith("Footprint IPC-7351B validation: PASS")
    assert certified.startswith("Footprint certification:")
    assert "IPC-7351 density recorded: B" in certified


def test_generate_footprint_reports_generator_failure(tmp_path: Path) -> None:
    service, upgrades = _service(tmp_path)

    result = service.generate_footprint_ipc7351("NOT-A-PACKAGE")

    assert result.startswith("Footprint generation failed:")
    assert upgrades == []


def test_validate_footprint_rejects_invalid_density_before_reading(tmp_path: Path) -> None:
    service, _ = _service(tmp_path)

    result = service.validate_footprint_ipc7351("missing.kicad_mod", "0805", density="Z")

    assert result == "Invalid density 'Z'. Must be A, B, or C."


def test_validate_footprint_reports_invalid_size_code(tmp_path: Path) -> None:
    service, _ = _service(tmp_path)
    relative = "generated/0805.kicad_mod"
    service.generate_footprint_ipc7351("0805", output_path=relative)

    result = service.validate_footprint_ipc7351(relative, "NOT-A-SIZE")

    assert result.startswith("Validation failed:")


def test_certify_footprint_preserves_path_and_missing_file_errors(tmp_path: Path) -> None:
    unsafe, _ = _service(tmp_path, resolve_error=ValueError("outside project"))
    assert unsafe.certify_footprint("../unsafe.kicad_mod") == (
        "Invalid footprint path: outside project"
    )

    service, _ = _service(tmp_path)
    assert service.certify_footprint("missing.kicad_mod") == (
        f"Footprint file not found: {tmp_path / 'missing.kicad_mod'}"
    )


def test_generate_named_package_with_pin_count_is_certifiable(tmp_path: Path) -> None:
    service, _ = _service(tmp_path)

    generated = service.generate_footprint_ipc7351("SOIC", pin_count=8)
    relative = "output/footprints/SOIC-8.kicad_mod"
    certified = service.certify_footprint(relative)

    assert "SOIC-8.kicad_mod" in generated
    assert "pad-count" in certified


def test_certify_footprint_reports_fail_for_missing_required_pads(tmp_path: Path) -> None:
    service, _ = _service(tmp_path)
    path = tmp_path / "fail.kicad_mod"
    path.write_text(
        """(footprint "SOIC-8"
  (fp_line (start -1 -1) (end 1 -1) (layer "F.CrtYd"))
  (fp_line (start -1 -1) (end 1 -1) (layer "F.Fab"))
  (fp_line (start -1 -1) (end 1 -1) (layer "F.SilkS"))
  (pad "1" smd rect (at 0 0) (size 1 1) (layers "F.Cu"))
  (pad "2" smd rect (at 0 0) (size 1 1) (layers "F.Cu"))
  (pad "3" smd rect (at 0 0) (size 1 1) (layers "F.Cu"))
  (pad "4" smd rect (at 0 0) (size 1 1) (layers "F.Cu"))
  (pad "5" smd rect (at 0 0) (size 1 1) (layers "F.Cu"))
  (pad "6" smd rect (at 0 0) (size 1 1) (layers "F.Cu")))\n""",
        encoding="utf-8",
    )

    result = service.certify_footprint("fail.kicad_mod")

    assert result.startswith("Footprint certification: FAIL")
    assert "pad-count" in result


def test_certify_footprint_reports_warn_for_missing_documentation_graphics(
    tmp_path: Path,
) -> None:
    service, _ = _service(tmp_path)
    path = tmp_path / "warn.kicad_mod"
    path.write_text(
        """(footprint "Custom"
  (fp_line (start -1 -1) (end 1 -1) (layer "F.CrtYd")))\n""",
        encoding="utf-8",
    )

    result = service.certify_footprint("warn.kicad_mod")

    assert result.startswith("Footprint certification: WARN")
    assert "documentation-layers" in result
