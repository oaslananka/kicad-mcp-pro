from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path
from types import ModuleType


def _module() -> ModuleType:
    spec = importlib.util.find_spec("kicad_mcp.library.catalog")
    assert spec is not None, "Library catalog service module must be extracted"
    return importlib.import_module("kicad_mcp.library.catalog")


def _service(tmp_path: Path):  # type: ignore[no-untyped-def]
    module = _module()
    symbol_dir = tmp_path / "symbols"
    symbol_dir.mkdir()
    (symbol_dir / "Device.kicad_sym").write_text("(kicad_symbol_lib)", encoding="utf-8")
    (symbol_dir / "MCU.kicad_sym").write_text("(kicad_symbol_lib)", encoding="utf-8")

    fp_a = tmp_path / "Resistor_SMD.pretty"
    fp_b = tmp_path / "Package_SO.pretty"
    fp_a.mkdir()
    fp_b.mkdir()
    (fp_a / "R_0805.kicad_mod").write_text(
        '(footprint "R_0805" (model "R_0805.wrl"))', encoding="utf-8"
    )
    (fp_a / "R_0603.kicad_mod").write_text('(footprint "R_0603")', encoding="utf-8")

    symbol_content = """(kicad_symbol_lib
  (symbol "R"
    (property "Description" "Resistor")
    (property "ki_keywords" "resistor R")
    (property "Datasheet" "https://example.com/r.pdf")
    (property "Footprint" "Resistor_SMD:R_0805")
    (pin passive line (name "A") (number "1"))
    (pin passive line (name "B") (number "2")))
  (symbol "R_Alias"
    (extends "R")))"""
    indexes = [
        {
            "Device:R": {
                "library": "Device",
                "name": "R",
                "description": "Resistor",
                "keywords": "resistor R",
            },
            "Device:R_Alias": {
                "library": "Device",
                "name": "R_Alias",
                "description": "Alias resistor",
                "keywords": "alias",
                "alias": "R",
            },
            "MCU:Controller": {
                "library": "MCU",
                "name": "Controller",
                "description": "Microcontroller",
                "keywords": "mcu",
            },
        }
    ]
    rebuild_calls: list[str] = []

    def read_symbol_file(library: str) -> str | None:
        return symbol_content if library == "Device" else None

    def rebuild_symbol_index() -> int:
        rebuild_calls.append("rebuild")
        return len(indexes[0])

    def footprint_file(library: str, footprint: str) -> Path:
        return {"Resistor_SMD": fp_a, "Package_SO": fp_b}.get(
            library, tmp_path / "missing"
        ) / f"{footprint}.kicad_mod"

    service = module.LibraryCatalogService(
        symbol_library_dir=lambda: symbol_dir,
        footprint_library_dirs=lambda: {"Resistor_SMD": fp_a, "Package_SO": fp_b},
        get_symbol_index=lambda: indexes[0],
        read_symbol_file=read_symbol_file,
        rebuild_symbol_index=rebuild_symbol_index,
        footprint_file=footprint_file,
        max_items_per_response=lambda: 1,
    )
    return service, rebuild_calls


def test_list_libraries_preserves_sorted_names_and_limits(tmp_path: Path) -> None:
    service, _ = _service(tmp_path)
    text = service.list_libraries()
    assert text == "\n".join(
        [
            "Symbol libraries (2 total):",
            "- Device",
            "- MCU",
            "",
            "Footprint libraries (2 total):",
            "- Package_SO.pretty",
            "- Resistor_SMD.pretty",
        ]
    )


def test_search_symbols_preserves_validation_filter_pagination_and_rendering(
    tmp_path: Path,
) -> None:
    service, _ = _service(tmp_path)
    assert service.search_symbols("R", page=0) == "page must be >= 1."
    assert service.search_symbols("R", page_size=0) == "page_size must be >= 1."
    assert service.search_symbols("missing") == "No symbols matched 'missing'."
    assert (
        service.search_symbols("R", library_filter="Device", page=3, page_size=1)
        == "Page 3 exceeds total pages (2)."
    )

    first = service.search_symbols("R", library_filter="device", page=1, page_size=1)
    assert "Symbol matches for 'R' (page 1/2, 1 shown, 2 total):" in first
    assert "- Device:R - Resistor [keywords: resistor R]" in first
    assert "... and 1 more matches (use page=2)" in first

    second = service.search_symbols("R", library_filter="Device", page=2, page_size=1)
    assert "- Device:R_Alias (alias: R) - Alias resistor [keywords: alias]" in second


def test_get_symbol_info_preserves_missing_properties_and_inherited_pins(tmp_path: Path) -> None:
    service, _ = _service(tmp_path)
    assert service.get_symbol_info("Missing", "R") == "Symbol library 'Missing' was not found."
    assert service.get_symbol_info("Device", "Missing") == "Symbol 'Device:Missing' was not found."

    text = service.get_symbol_info("Device", "R")
    assert "Symbol: Device:R" in text
    assert "- Description: Resistor" in text
    assert "- Keywords: resistor R" in text
    assert "- Default footprint: Resistor_SMD:R_0805" in text
    assert "- Datasheet: https://example.com/r.pdf" in text
    assert "- Pins: 2" in text
    assert "  - 1 A (passive)" in text

    alias = service.get_symbol_info("Device", "R_Alias")
    assert "Symbol: Device:R_Alias" in alias
    assert "- Pins: 2" in alias


def test_search_footprints_preserves_filter_validation_and_pagination(tmp_path: Path) -> None:
    service, _ = _service(tmp_path)
    assert service.search_footprints("R", page=0) == "page must be >= 1."
    assert service.search_footprints("R", page_size=0) == "page_size must be >= 1."
    assert service.search_footprints("missing") == "No footprints matched 'missing'."
    text = service.search_footprints("R_", library_filter="resistor", page=1, page_size=1)
    assert "Footprint matches for 'R_' (page 1/2, 1 shown, 2 total):" in text
    assert "... and 1 more matches (use page=2)" in text
    assert service.search_footprints("R_", page=3, page_size=1) == "Page 3 exceeds total pages (2)."


def test_list_rebuild_and_footprint_details_preserve_exact_behavior(tmp_path: Path) -> None:
    service, rebuild_calls = _service(tmp_path)
    listed = service.list_footprints("Resistor_SMD")
    assert listed == "Footprints in Resistor_SMD (2 total):\n- R_0603"
    assert service.list_footprints("Missing") == "Footprint library 'Missing' was not found."

    assert service.rebuild_index() == "Rebuilt the symbol index with 3 entries."
    assert rebuild_calls == ["rebuild"]

    info = service.get_footprint_info("Resistor_SMD", "R_0805")
    footprint_path = tmp_path / "Resistor_SMD.pretty" / "R_0805.kicad_mod"
    expected = f"Footprint: Resistor_SMD:R_0805\n- File: {footprint_path}\n- 3D model: R_0805.wrl"
    assert info == expected
    no_model = service.get_footprint_info("Resistor_SMD", "R_0603")
    assert no_model.endswith("- 3D model: (none)")
    assert service.get_footprint_info("Missing", "X") == "Footprint 'Missing:X' was not found."

    assert service.get_footprint_3d_model("Resistor_SMD", "R_0805") == "R_0805.wrl"
    assert (
        service.get_footprint_3d_model("Resistor_SMD", "R_0603")
        == "Footprint 'Resistor_SMD:R_0603' does not define a 3D model."
    )
    assert service.get_footprint_3d_model("Missing", "X") == "Footprint 'Missing:X' was not found."
