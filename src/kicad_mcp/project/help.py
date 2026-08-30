"""Project startup quick-start rendering independent of FastMCP."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

_QUICK_START_LINES = (
    "# KiCad MCP Pro Quick Start",
    "",
    "1. Call `kicad_get_version()` to verify the runtime.",
    "2. Call `kicad_set_project()` or `kicad_create_new_project()`.",
    "3. Inspect `kicad://project/info` and `kicad://board/summary`.",
    "4. Call `kicad_list_tool_categories()` to discover the right tool family.",
    "",
    "Available categories:",
)


@dataclass(frozen=True, slots=True)
class ProjectHelpService:
    """Render the startup quick-start guide from tool categories and profiles."""

    category_descriptions: Callable[[], Mapping[str, str]]
    available_profiles: Callable[[], list[str]]

    def help_text(self) -> str:
        lines = list(_QUICK_START_LINES)
        for category, description in self.category_descriptions().items():
            lines.append(f"- `{category}`: {description}")
        lines.append("")
        lines.append("Profiles:")
        lines.extend(f"- `{profile}`" for profile in self.available_profiles())
        return "\n".join(lines)
