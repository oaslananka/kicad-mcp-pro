from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import TextIO

from kicad_mcp.schematic.template_instantiation import (
    SchematicTemplateInstantiationService,
)

YamlLoader = Callable[[TextIO], object]


def _service(
    templates_dir: Path,
    *,
    documents: Mapping[str, object] | None = None,
    loader_factory: Callable[[], YamlLoader] | None = None,
) -> SchematicTemplateInstantiationService:
    data = documents or {}

    def load(stream: TextIO) -> object:
        return data[Path(stream.name).name]

    return SchematicTemplateInstantiationService(
        templates_dir=templates_dir,
        yaml_loader_factory=loader_factory or (lambda: load),
    )


def test_instantiate_reports_missing_name_with_sorted_available_files(tmp_path: Path) -> None:
    templates = tmp_path / "templates"
    templates.mkdir()
    (templates / "zeta.yaml").write_text("ignored", encoding="utf-8")
    (templates / "alpha.yaml").write_text("ignored", encoding="utf-8")
    loaded = False

    def factory() -> YamlLoader:
        nonlocal loaded
        loaded = True
        raise AssertionError("loader must not be requested")

    result = _service(templates, loader_factory=factory).instantiate("missing", prefix=" TEST ")

    assert result == "Template 'missing' not found. Available: alpha, zeta"
    assert loaded is False


def test_instantiate_preserves_pyyaml_and_parse_errors(tmp_path: Path) -> None:
    templates = tmp_path / "templates"
    templates.mkdir()
    (templates / "demo.yaml").write_text("ignored", encoding="utf-8")

    def missing_factory() -> YamlLoader:
        raise ModuleNotFoundError("yaml")

    def bad_load(_stream: TextIO) -> object:
        raise ValueError("invalid mapping")

    assert _service(templates, loader_factory=missing_factory).instantiate("demo") == (
        "Template tools require PyYAML. Install it to instantiate templates."
    )
    assert _service(templates, loader_factory=lambda: bad_load).instantiate("demo") == (
        "Could not parse template 'demo': invalid mapping"
    )


def test_instantiate_renders_exact_action_plan_with_overrides(tmp_path: Path) -> None:
    templates = tmp_path / "templates"
    templates.mkdir()
    (templates / "demo.yaml").write_text("ignored", encoding="utf-8")
    documents: dict[str, object] = {
        "demo.yaml": {
            "name": "Demo Supply",
            "parameters": {
                "vin": {"default": 12},
                "mode": {"default": "eco"},
            },
            "symbols": [
                {
                    "ref_prefix": "U",
                    "value": "REG",
                    "comment": "Controller",
                    "default_footprint": "Package_SO:SOIC-8",
                },
                {
                    "value": "C",
                    "comment": "Output capacitor",
                },
            ],
            "nets": [
                {"name": "VIN", "type": "power", "note": "Input rail"},
                {"name": "SW"},
            ],
            "part_search_hints": {
                "controller": "{vin}V {mode} regulator",
                "capacitor": "capacitor {extra}",
            },
            "placement_hints": ["Keep loop short", "Place capacitor close"],
        }
    }

    result = _service(templates, documents=documents).instantiate(
        "demo",
        prefix="  AUD_  ",
        params={"vin": 5.0, "extra": "low-esr"},
    )

    assert result == "\n".join(
        [
            "# Instantiation Plan: Demo Supply",
            "Prefix: `AUD_`",
            "",
            "## Parameters",
            "- vin: **5.0**",
            "- mode: **eco**",
            "- extra: **low-esr**",
            "",
            "## Step 1: Add Symbols",
            "Call sch_add_symbol() for each symbol below:",
            "",
            "- `sch_add_symbol(reference='AUD_U1', value='REG')`",
            "  Comment: Controller",
            "  Footprint hint: Package_SO:SOIC-8",
            "- `sch_add_symbol(reference='AUD_X2', value='C')`",
            "  Comment: Output capacitor",
            "  Footprint hint: —",
            "",
            "## Step 2: Add Nets / Wires",
            "Call sch_add_power_symbol() and sch_add_wire() to connect:",
            "",
            "- `VIN` — power (Input rail)",
            "- `SW` — signal",
            "",
            "## Step 3: Part Selection",
            "- **controller**: `lib_recommend_part(category='5.0V eco regulator')`",
            "- **capacitor**: `lib_recommend_part(category='capacitor low-esr')`",
            "",
            "## Step 4: Footprint Assignment",
            (
                "For each symbol: `lib_bind_part_to_symbol(sym_ref, lcsc_code, "
                "auto_assign_footprint=True)`"
            ),
            "",
            "## Placement Hints",
            "- Keep loop short",
            "- Place capacitor close",
        ]
    )


def test_instantiate_preserves_empty_search_and_hint_fallbacks(tmp_path: Path) -> None:
    templates = tmp_path / "templates"
    templates.mkdir()
    (templates / "minimal.yaml").write_text("ignored", encoding="utf-8")
    documents: dict[str, object] = {
        "minimal.yaml": {
            "symbols": [],
            "nets": [],
            "parameters": {},
        }
    }

    result = _service(templates, documents=documents).instantiate("minimal")

    assert result == "\n".join(
        [
            "# Instantiation Plan: minimal",
            "Prefix: `(none)`",
            "",
            "## Parameters",
            "",
            "## Step 1: Add Symbols",
            "Call sch_add_symbol() for each symbol below:",
            "",
            "",
            "## Step 2: Add Nets / Wires",
            "Call sch_add_power_symbol() and sch_add_wire() to connect:",
            "",
            "",
            "## Step 3: Part Selection",
            "- Use lib_search_components() or lib_recommend_part() for each symbol.",
            "",
            "## Step 4: Footprint Assignment",
            (
                "For each symbol: `lib_bind_part_to_symbol(sym_ref, lcsc_code, "
                "auto_assign_footprint=True)`"
            ),
            "",
            "## Placement Hints",
        ]
    )
