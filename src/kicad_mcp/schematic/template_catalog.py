"""FastMCP-independent bundled subcircuit template catalog services."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TextIO

YamlLoader = Callable[[TextIO], Any]


@dataclass(frozen=True)
class SchematicTemplateCatalogService:
    """Discover and render bundled subcircuit template metadata."""

    templates_dir: Path
    yaml_loader_factory: Callable[[], YamlLoader]

    def list_templates(self) -> str:
        if not self.templates_dir.exists():
            return "No subcircuit templates are available."

        try:
            load_yaml = self.yaml_loader_factory()
        except ImportError:
            return "Template tools require PyYAML. Install it to inspect bundled templates."

        lines = ["# Available Subcircuit Templates", ""]
        for yaml_file in sorted(self.templates_dir.glob("*.yaml")):
            try:
                with yaml_file.open(encoding="utf-8") as stream:
                    data = load_yaml(stream)
                name = data.get("name", yaml_file.stem)
                description = str(data.get("description", "")).strip().split("\n")[0][:80]
                parameters = list(data.get("parameters", {}).keys())
                lines.append(f"**{name}**")
                lines.append(f"  {description}")
                if parameters:
                    lines.append(f"  Parameters: {', '.join(parameters)}")
                lines.append("")
            except Exception:
                lines.append(f"**{yaml_file.stem}** — (could not parse template)")
                lines.append("")

        if len(lines) == 2:
            return "No subcircuit templates were found."

        lines.append("Use sch_instantiate_template(template_name, prefix, params) to add.")
        return "\n".join(lines)

    def template_info(self, template_name: str) -> str:
        yaml_file = self.templates_dir / f"{template_name}.yaml"
        if not yaml_file.exists():
            available = [path.stem for path in self.templates_dir.glob("*.yaml")]
            return (
                f"Template '{template_name}' not found. Available: {', '.join(sorted(available))}"
            )

        try:
            load_yaml = self.yaml_loader_factory()
            with yaml_file.open(encoding="utf-8") as stream:
                data = load_yaml(stream)
        except ImportError:
            return "Template tools require PyYAML. Install it to inspect bundled templates."
        except Exception as exc:
            return f"Could not parse template '{template_name}': {exc}"

        lines = [
            f"# Template: {data.get('name', template_name)}",
            f"Version: {data.get('version', '1.0')}",
            "",
            data.get("description", "").strip(),
            "",
        ]

        parameters = data.get("parameters", {})
        if parameters:
            lines += ["## Parameters", ""]
            for parameter_name, definition in parameters.items():
                lines.append(
                    f"- **{parameter_name}** ({definition.get('type', 'any')}): "
                    f"{definition.get('description', '')} "
                    f"[default: {definition.get('default', '—')}]"
                )
            lines.append("")

        symbols = data.get("symbols", [])
        if symbols:
            lines += [f"## Symbols ({len(symbols)})", ""]
            for symbol in symbols:
                lines.append(
                    f"- **{symbol.get('ref_prefix', '?')}?** "
                    f"{symbol.get('value', '?')} — {symbol.get('comment', '')}"
                )
                left_pins = ", ".join(str(pin) for pin in symbol.get("pins_left", []))
                right_pins = ", ".join(str(pin) for pin in symbol.get("pins_right", []))
                pin_parts: list[str] = []
                if left_pins:
                    pin_parts.append(f"left: {left_pins}")
                if right_pins:
                    pin_parts.append(f"right: {right_pins}")
                if pin_parts:
                    lines.append(f"  Pins: {' | '.join(pin_parts)}")
            lines.append("")

        nets = data.get("nets", [])
        if nets:
            lines += ["## Nets", ""]
            for net in nets:
                note = f" — {net['note']}" if net.get("note") else ""
                lines.append(f"- `{net['name']}` ({net.get('type', 'signal')}){note}")
            lines.append("")

        placement_hints = data.get("placement_hints", [])
        if placement_hints:
            lines += ["## Placement Hints", ""]
            for hint in placement_hints:
                lines.append(f"- {hint}")
            lines.append("")

        search_hints = data.get("part_search_hints", {})
        if search_hints:
            lines += ["## Part Search Hints (use with lib_recommend_part())", ""]
            for role, query in search_hints.items():
                lines.append(f"- {role}: `{query}`")

        return "\n".join(lines)
