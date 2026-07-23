from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import TextIO

from kicad_mcp.schematic.template_catalog import SchematicTemplateCatalogService

YamlLoader = Callable[[TextIO], object]


def _service(
    templates_dir: Path,
    *,
    documents: Mapping[str, object] | None = None,
    loader_factory: Callable[[], YamlLoader] | None = None,
) -> SchematicTemplateCatalogService:
    data = documents or {}

    def load(stream: TextIO) -> object:
        return data[Path(stream.name).name]

    return SchematicTemplateCatalogService(
        templates_dir=templates_dir,
        yaml_loader_factory=loader_factory or (lambda: load),
    )


def test_list_templates_returns_missing_directory_before_loading_yaml(tmp_path: Path) -> None:
    loaded = False

    def factory() -> YamlLoader:
        nonlocal loaded
        loaded = True
        raise AssertionError("loader must not be requested")

    result = _service(tmp_path / "missing", loader_factory=factory).list_templates()

    assert result == "No subcircuit templates are available."
    assert loaded is False


def test_list_templates_preserves_lazy_pyyaml_error(tmp_path: Path) -> None:
    templates = tmp_path / "templates"
    templates.mkdir()

    def factory() -> YamlLoader:
        raise ModuleNotFoundError("yaml")

    assert _service(templates, loader_factory=factory).list_templates() == (
        "Template tools require PyYAML. Install it to inspect bundled templates."
    )


def test_list_templates_returns_empty_catalog_message(tmp_path: Path) -> None:
    templates = tmp_path / "templates"
    templates.mkdir()

    assert _service(templates).list_templates() == "No subcircuit templates were found."


def test_list_templates_sorts_files_and_preserves_formatting(tmp_path: Path) -> None:
    templates = tmp_path / "templates"
    templates.mkdir()
    (templates / "zeta.yaml").write_text("ignored", encoding="utf-8")
    (templates / "alpha.yaml").write_text("ignored", encoding="utf-8")
    long_first_line = "A" * 90
    documents: dict[str, object] = {
        "alpha.yaml": {
            "description": f"{long_first_line}\nsecond line",
            "parameters": {"vin": {}, "vout": {}},
        },
        "zeta.yaml": {
            "name": "Zeta Template",
            "description": "Simple template",
            "parameters": {},
        },
    }

    result = _service(templates, documents=documents).list_templates()

    assert result == "\n".join(
        [
            "# Available Subcircuit Templates",
            "",
            "**alpha**",
            f"  {'A' * 80}",
            "  Parameters: vin, vout",
            "",
            "**Zeta Template**",
            "  Simple template",
            "",
            "Use sch_instantiate_template(template_name, prefix, params) to add.",
        ]
    )


def test_list_templates_continues_after_per_file_parse_failure(tmp_path: Path) -> None:
    templates = tmp_path / "templates"
    templates.mkdir()
    (templates / "bad.yaml").write_text("bad", encoding="utf-8")
    (templates / "good.yaml").write_text("good", encoding="utf-8")

    def load(stream: TextIO) -> object:
        if Path(stream.name).name == "bad.yaml":
            raise ValueError("broken yaml")
        return {"name": "Good", "description": "Works"}

    result = _service(templates, loader_factory=lambda: load).list_templates()

    assert result == "\n".join(
        [
            "# Available Subcircuit Templates",
            "",
            "**bad** — (could not parse template)",
            "",
            "**Good**",
            "  Works",
            "",
            "Use sch_instantiate_template(template_name, prefix, params) to add.",
        ]
    )


def test_template_info_reports_missing_name_with_sorted_available_files(tmp_path: Path) -> None:
    templates = tmp_path / "templates"
    templates.mkdir()
    (templates / "zeta.yaml").write_text("ignored", encoding="utf-8")
    (templates / "alpha.yaml").write_text("ignored", encoding="utf-8")

    assert _service(templates).template_info("missing") == (
        "Template 'missing' not found. Available: alpha, zeta"
    )


def test_template_info_checks_existence_before_loading_yaml(tmp_path: Path) -> None:
    templates = tmp_path / "templates"
    templates.mkdir()
    loaded = False

    def factory() -> YamlLoader:
        nonlocal loaded
        loaded = True
        raise ModuleNotFoundError("yaml")

    result = _service(templates, loader_factory=factory).template_info("missing")

    assert result == "Template 'missing' not found. Available: "
    assert loaded is False


def test_template_info_preserves_pyyaml_and_parse_errors(tmp_path: Path) -> None:
    templates = tmp_path / "templates"
    templates.mkdir()
    (templates / "demo.yaml").write_text("ignored", encoding="utf-8")

    def missing_factory() -> YamlLoader:
        raise ImportError("yaml")

    def bad_load(_stream: TextIO) -> object:
        raise ValueError("invalid mapping")

    assert _service(templates, loader_factory=missing_factory).template_info("demo") == (
        "Template tools require PyYAML. Install it to inspect bundled templates."
    )
    assert _service(templates, loader_factory=lambda: bad_load).template_info("demo") == (
        "Could not parse template 'demo': invalid mapping"
    )


def test_template_info_renders_all_sections_in_source_order(tmp_path: Path) -> None:
    templates = tmp_path / "templates"
    templates.mkdir()
    (templates / "demo.yaml").write_text("ignored", encoding="utf-8")
    documents: dict[str, object] = {
        "demo.yaml": {
            "name": "Demo Supply",
            "version": "2.1",
            "description": "Two-line description.\nSecond line.",
            "parameters": {
                "vin": {
                    "type": "voltage",
                    "description": "Input voltage",
                    "default": 12,
                },
                "mode": {"description": "Operating mode"},
            },
            "symbols": [
                {
                    "ref_prefix": "U",
                    "value": "REG",
                    "comment": "Controller",
                    "pins_left": ["VIN", 2],
                    "pins_right": ["VOUT"],
                },
                {
                    "value": "C",
                    "pins_left": [],
                    "pins_right": [],
                },
            ],
            "nets": [
                {"name": "VIN", "type": "power", "note": "Input rail"},
                {"name": "SW"},
            ],
            "placement_hints": ["Keep loop short", "Place capacitor close"],
            "part_search_hints": {
                "controller": "buck regulator",
                "inductor": "shielded inductor",
            },
        }
    }

    result = _service(templates, documents=documents).template_info("demo")

    assert result == "\n".join(
        [
            "# Template: Demo Supply",
            "Version: 2.1",
            "",
            "Two-line description.\nSecond line.",
            "",
            "## Parameters",
            "",
            "- **vin** (voltage): Input voltage [default: 12]",
            "- **mode** (any): Operating mode [default: —]",
            "",
            "## Symbols (2)",
            "",
            "- **U?** REG — Controller",
            "  Pins: left: VIN, 2 | right: VOUT",
            "- **??** C — ",
            "",
            "## Nets",
            "",
            "- `VIN` (power) — Input rail",
            "- `SW` (signal)",
            "",
            "## Placement Hints",
            "",
            "- Keep loop short",
            "- Place capacitor close",
            "",
            "## Part Search Hints (use with lib_recommend_part())",
            "",
            "- controller: `buck regulator`",
            "- inductor: `shielded inductor`",
        ]
    )


def test_template_info_uses_defaults_and_omits_empty_sections(tmp_path: Path) -> None:
    templates = tmp_path / "templates"
    templates.mkdir()
    (templates / "minimal.yaml").write_text("ignored", encoding="utf-8")

    result = _service(
        templates,
        documents={"minimal.yaml": {"description": "  Minimal  "}},
    ).template_info("minimal")

    assert result == "\n".join(
        [
            "# Template: minimal",
            "Version: 1.0",
            "",
            "Minimal",
            "",
        ]
    )
