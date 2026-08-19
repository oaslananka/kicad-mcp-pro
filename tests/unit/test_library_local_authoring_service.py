from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path
from types import ModuleType

from kicad_mcp.utils.sexpr import _extract_block, _sexpr_string


def _module() -> ModuleType:
    spec = importlib.util.find_spec("kicad_mcp.library.local_authoring")
    assert spec is not None, "Library local-authoring service must be extracted"
    return importlib.import_module("kicad_mcp.library.local_authoring")


def test_assign_footprint_preserves_missing_and_update_behavior(tmp_path: Path) -> None:
    module = _module()
    updates: list[tuple[str, str, str]] = []
    existing = tmp_path / "R_0805.kicad_mod"
    existing.write_text("(footprint)", encoding="utf-8")

    def footprint_file(library: str, footprint: str) -> Path:
        if (library, footprint) == ("Resistor_SMD", "R_0805"):
            return existing
        return tmp_path / "missing.kicad_mod"

    service = module.LibraryLocalAuthoringService(
        footprint_file=footprint_file,
        update_symbol_property=lambda ref, field, value: updates.append((ref, field, value)),
        project_dir=lambda: tmp_path,
    )

    assert (
        service.assign_footprint("R1", "Missing", "Nope")
        == "Footprint 'Missing:Nope' was not found."
    )
    assert updates == []
    assert (
        service.assign_footprint("R1", "Resistor_SMD", "R_0805")
        == "Assigned footprint 'Resistor_SMD:R_0805' to 'R1'."
    )
    assert updates == [("R1", "Footprint", "Resistor_SMD:R_0805")]


def test_create_custom_symbol_requires_active_project() -> None:
    module = _module()
    service = module.LibraryLocalAuthoringService(
        footprint_file=lambda _library, _footprint: Path("missing"),
        update_symbol_property=lambda _ref, _field, _value: None,
        project_dir=lambda: None,
    )

    assert service.create_custom_symbol("Demo", []) == "No active project is configured."


def test_create_custom_symbol_preserves_defaults_and_file_shape(tmp_path: Path) -> None:
    module = _module()
    upgrades: list[Path] = []
    service = module.LibraryLocalAuthoringService(
        footprint_file=lambda _library, _footprint: Path("missing"),
        update_symbol_property=lambda _ref, _field, _value: None,
        project_dir=lambda: tmp_path,
        upgrade_symbol_library=lambda path: upgrades.append(path),
    )

    result = service.create_custom_symbol("Demo", [{}, {"number": "A", "name": "VIN"}])
    library_file = tmp_path / "custom_symbols.kicad_sym"
    content = library_file.read_text(encoding="utf-8")

    assert result == f"Created custom symbol 'Demo' in {library_file}."
    assert upgrades == [library_file]
    assert content.startswith('(kicad_symbol_lib (version 20250316) (generator "kicad-mcp-pro")\n')
    assert '\t(symbol "Demo"' in content
    assert "(at 0.0 0.0 180)" in content
    assert "(at 0.0 -2.54 180)" in content
    assert '(number "1"' in content
    assert '(name "PIN1"' in content
    assert '(number "A"' in content
    assert '(name "VIN"' in content


def test_create_custom_symbol_appends_and_escapes_sexpr_strings(tmp_path: Path) -> None:
    module = _module()
    library_file = tmp_path / "custom_symbols.kicad_sym"
    library_file.write_text(
        '(kicad_symbol_lib (version 20250316) (generator "kicad-mcp-pro")\n)\n',
        encoding="utf-8",
    )
    service = module.LibraryLocalAuthoringService(
        footprint_file=lambda _library, _footprint: Path("missing"),
        update_symbol_property=lambda _ref, _field, _value: None,
        project_dir=lambda: tmp_path,
    )
    name = 'Bad")\n\t(symbol "Injected"'
    pin_name = 'PIN")\n\t(pin output line'

    text = service.create_custom_symbol(
        name,
        [{"number": '1")\n\t(number "9"', "name": pin_name}],
    )
    content = library_file.read_text(encoding="utf-8")
    start = content.index(f"\t(symbol {_sexpr_string(name)}")
    block, consumed = _extract_block(content, start)

    assert text == f"Created custom symbol '{name}' in {library_file}."
    assert consumed > 0
    assert '\n\t(symbol "Injected"' not in content
    assert "\n\t(pin output line" not in block
    assert _sexpr_string(pin_name) in block


class _UpgradeResult:
    def __init__(self, *, upgraded: bool, detail: str = "") -> None:
        self.upgraded = upgraded
        self.detail = detail


def _pin_table_service(
    tmp_path: Path,
    *,
    upgraded: bool = True,
):
    module = _module()
    upgrades: list[Path] = []

    def upgrade(path: Path) -> _UpgradeResult:
        upgrades.append(path)
        return _UpgradeResult(upgraded=upgraded, detail="cli unavailable")

    service = module.LibraryLocalAuthoringService(
        footprint_file=lambda _library, _footprint: Path("missing"),
        update_symbol_property=lambda _ref, _field, _value: None,
        project_dir=lambda: tmp_path,
        upgrade_symbol_library=upgrade,
        resolve_within_project=lambda relative: tmp_path / relative,
        default_output_dir=lambda: tmp_path / "output",
    )
    return service, upgrades


def test_generate_symbol_from_pintable_preserves_custom_path_and_migration_note(
    tmp_path: Path,
) -> None:
    service, upgrades = _pin_table_service(tmp_path, upgraded=False)

    result = service.generate_symbol_from_pintable(
        "Demo IC",
        [
            {"number": "1", "name": "VIN", "pin_type": "power_in", "side": "left"},
            {"number": "2", "name": "VOUT", "pin_type": "power_out", "side": "right"},
        ],
        reference_prefix="U",
        description="Demo regulator",
        datasheet="https://example.invalid/demo.pdf",
        footprint_hint="Package_SO:SOIC-8_3.9x4.9mm_P1.27mm",
        output_path="custom/Demo.kicad_sym",
    )

    path = tmp_path / "custom" / "Demo.kicad_sym"
    assert path.exists()
    content = path.read_text(encoding="utf-8")
    assert content.startswith("(kicad_symbol_lib")
    assert 'property "Reference" "U"' in content
    assert 'property "Description" "Demo regulator"' in content
    assert upgrades == [path]
    assert result.startswith(f"Symbol saved to {path}\nName: Demo IC, Pins: 2, Ref prefix: U")
    assert "Format note: kept repository writer dialect" in result
    assert "cli unavailable" in result


def test_generate_symbol_from_pintable_preserves_default_output_name(tmp_path: Path) -> None:
    service, upgrades = _pin_table_service(tmp_path)

    result = service.generate_symbol_from_pintable(
        "Demo/IC",
        [{"number": 1, "name": "A"}],
        reference_prefix="J",
    )

    path = tmp_path / "output" / "symbols" / "Demo_IC.kicad_sym"
    assert path.exists()
    assert upgrades == [path]
    assert result.startswith(f"Symbol saved to {path}\nName: Demo/IC, Pins: 1, Ref prefix: J")
    assert "Format note:" not in result


def test_generate_symbol_from_pintable_reports_invalid_pin_specification(tmp_path: Path) -> None:
    service, upgrades = _pin_table_service(tmp_path)

    result = service.generate_symbol_from_pintable("Demo", [{"number": "1"}])

    assert result.startswith("Invalid pin specification:")
    assert "raw: {'number': '1'}" in result
    assert upgrades == []


def test_generate_symbol_from_pintable_reports_generation_failure(tmp_path: Path) -> None:
    service, upgrades = _pin_table_service(tmp_path)

    result = service.generate_symbol_from_pintable(
        "Demo",
        [{"number": "1", "name": "A", "side": "diagonal"}],
    )

    assert result.startswith("Symbol generation failed:")
    assert upgrades == []


def test_generate_symbol_from_pintable_requires_resolver_for_custom_path(tmp_path: Path) -> None:
    module = _module()
    service = module.LibraryLocalAuthoringService(
        footprint_file=lambda _library, _footprint: Path("missing"),
        update_symbol_property=lambda _ref, _field, _value: None,
        project_dir=lambda: tmp_path,
    )

    result = service.generate_symbol_from_pintable(
        "Demo",
        [{"number": "1", "name": "A"}],
        output_path="custom/Demo.kicad_sym",
    )

    assert result == "No project path resolver is configured."


def test_generate_symbol_from_pintable_falls_back_to_project_output(tmp_path: Path) -> None:
    module = _module()
    service = module.LibraryLocalAuthoringService(
        footprint_file=lambda _library, _footprint: Path("missing"),
        update_symbol_property=lambda _ref, _field, _value: None,
        project_dir=lambda: tmp_path,
    )

    result = service.generate_symbol_from_pintable(
        "Fallback",
        [{"number": "1", "name": "A"}],
    )

    path = tmp_path / "output" / "symbols" / "Fallback.kicad_sym"
    assert path.exists()
    assert result.startswith(f"Symbol saved to {path}")


def test_generate_symbol_from_pintable_requires_project_for_fallback_output() -> None:
    module = _module()
    service = module.LibraryLocalAuthoringService(
        footprint_file=lambda _library, _footprint: Path("missing"),
        update_symbol_property=lambda _ref, _field, _value: None,
        project_dir=lambda: None,
    )

    result = service.generate_symbol_from_pintable(
        "Demo",
        [{"number": "1", "name": "A"}],
    )

    assert result == "No active project is configured."
