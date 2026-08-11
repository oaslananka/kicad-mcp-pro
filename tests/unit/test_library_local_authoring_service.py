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
    service = module.LibraryLocalAuthoringService(
        footprint_file=lambda _library, _footprint: Path("missing"),
        update_symbol_property=lambda _ref, _field, _value: None,
        project_dir=lambda: tmp_path,
    )

    result = service.create_custom_symbol("Demo", [{}, {"number": "A", "name": "VIN"}])
    library_file = tmp_path / "custom_symbols.kicad_sym"
    content = library_file.read_text(encoding="utf-8")

    assert result == f"Created custom symbol 'Demo' in {library_file}."
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
