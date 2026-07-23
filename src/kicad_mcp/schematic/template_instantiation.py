"""FastMCP-independent bundled subcircuit template instantiation services."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TextIO

YamlLoader = Callable[[TextIO], Any]


@dataclass(frozen=True)
class SchematicTemplateInstantiationService:
    """Render action plans for bundled subcircuit templates."""

    templates_dir: Path
    yaml_loader_factory: Callable[[], YamlLoader]

    def instantiate(
        self,
        template_name: str,
        prefix: str = "",
        params: dict[str, object] | None = None,
    ) -> str:
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
            return "Template tools require PyYAML. Install it to instantiate templates."
        except Exception as exc:
            return f"Could not parse template '{template_name}': {exc}"

        params = params or {}
        defaults = {key: value.get("default") for key, value in data.get("parameters", {}).items()}
        resolved = {**defaults, **params}

        symbols = data.get("symbols", [])
        nets = data.get("nets", [])
        hints = data.get("placement_hints", [])
        search = data.get("part_search_hints", {})
        prefix_str = prefix.strip()

        lines = [
            f"# Instantiation Plan: {data.get('name', template_name)}",
            f"Prefix: `{prefix_str or '(none)'}`",
            "",
            "## Parameters",
        ]
        for key, value in resolved.items():
            lines.append(f"- {key}: **{value}**")

        lines += [
            "",
            "## Step 1: Add Symbols",
            "Call sch_add_symbol() for each symbol below:",
            "",
        ]
        for index, symbol in enumerate(symbols, start=1):
            reference = f"{prefix_str}{symbol.get('ref_prefix', 'X')}{index}"
            lines.append(
                f"- `sch_add_symbol(reference={reference!r}, value={symbol.get('value', '?')!r})`"
            )
            lines.append(f"  Comment: {symbol.get('comment', '')}")
            lines.append(f"  Footprint hint: {symbol.get('default_footprint', '—')}")

        lines += [
            "",
            "## Step 2: Add Nets / Wires",
            "Call sch_add_power_symbol() and sch_add_wire() to connect:",
            "",
        ]
        for net in nets:
            note = f" ({net['note']})" if net.get("note") else ""
            lines.append(f"- `{net['name']}` — {net.get('type', 'signal')}{note}")

        lines += ["", "## Step 3: Part Selection"]
        if search:
            for role, query_template in search.items():
                query = str(query_template)
                for key, value in resolved.items():
                    query = query.replace(f"{{{key}}}", str(value))
                lines.append(f"- **{role}**: `lib_recommend_part(category={query!r})`")
        else:
            lines.append("- Use lib_search_components() or lib_recommend_part() for each symbol.")

        lines += [
            "",
            "## Step 4: Footprint Assignment",
            (
                "For each symbol: `lib_bind_part_to_symbol(sym_ref, lcsc_code, "
                "auto_assign_footprint=True)`"
            ),
            "",
            "## Placement Hints",
        ]
        for hint in hints:
            lines.append(f"- {hint}")

        return "\n".join(lines)
