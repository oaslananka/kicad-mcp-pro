from __future__ import annotations

import argparse
import contextlib
import inspect
import io
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from mcp.types import ToolAnnotations

from kicad_mcp.config import reset_config
from kicad_mcp.server import build_server
from kicad_mcp.tools.metadata import get_tool_metadata, infer_tool_annotations
from kicad_mcp.tools.router import available_profiles

ROOT = Path(__file__).resolve().parents[1]
DOC_PATH = ROOT / "docs" / "tools-reference.md"
GENERATED_PATH = ROOT / "docs" / "tools-reference.generated.md"
SECTION_HEADING = "## Complete Tool Catalog"


@dataclass(frozen=True)
class ToolRow:
    name: str
    profiles: tuple[str, ...]
    read_only: bool
    destructive: bool
    open_world: bool
    idempotent: bool
    headless: bool
    requires_kicad_running: bool
    summary: str


def _registered_tools(profile: str) -> dict[str, object]:
    previous_mode = os.environ.get("KICAD_MCP_OPERATING_MODE")
    os.environ["KICAD_MCP_OPERATING_MODE"] = "experimental"
    reset_config()
    buffer = io.StringIO()
    try:
        with contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(buffer):
            server = build_server(profile=profile)
        server.filter_runtime_tools = False
        return {tool.name: tool for tool in server.list_tools_sync()}
    finally:
        if previous_mode is None:
            os.environ.pop("KICAD_MCP_OPERATING_MODE", None)
        else:
            os.environ["KICAD_MCP_OPERATING_MODE"] = previous_mode
        reset_config()


def _annotation_bool(annotations: ToolAnnotations, field: str) -> bool:
    return bool(getattr(annotations, field, False))


def _summary(tool: object) -> str:
    fn = getattr(tool, "fn", None)
    doc = inspect.getdoc(fn) if fn is not None else None
    text = doc or str(getattr(tool, "description", "") or "")
    first_line = text.strip().splitlines()[0] if text.strip() else "No summary available."
    first_line = " ".join(first_line.split()).replace("|", "\\|")
    if len(first_line) > 120:
        return first_line[:117].rstrip() + "..."
    return first_line


def _yes(value: bool) -> str:
    return "yes" if value else "no"


def collect_rows() -> list[ToolRow]:
    profile_tools: dict[str, dict[str, object]] = {
        profile: _registered_tools(profile) for profile in available_profiles()
    }
    all_tools: dict[str, object] = {}
    tool_profiles: dict[str, list[str]] = {}

    for profile, tools in profile_tools.items():
        for name, tool in tools.items():
            all_tools.setdefault(name, tool)
            tool_profiles.setdefault(name, []).append(profile)

    rows: list[ToolRow] = []
    all_profile_names = set(profile_tools)
    for name in sorted(all_tools):
        metadata = get_tool_metadata(name)
        annotations = infer_tool_annotations(name)
        profiles = tuple(sorted(tool_profiles[name]))
        profile_value = ("all",) if set(profiles) == all_profile_names else profiles
        rows.append(
            ToolRow(
                name=name,
                profiles=profile_value,
                read_only=_annotation_bool(annotations, "read_only_hint"),
                destructive=_annotation_bool(annotations, "destructive_hint"),
                open_world=_annotation_bool(annotations, "open_world_hint"),
                idempotent=_annotation_bool(annotations, "idempotent_hint"),
                headless=bool(metadata and metadata.headless_compatible),
                requires_kicad_running=bool(metadata and metadata.requires_kicad_running),
                summary=_summary(all_tools[name]),
            )
        )
    return rows


def render_generated(rows: list[ToolRow]) -> str:
    lines = [
        "Machine-maintained catalog. Refresh with `pnpm run docs:tools`.",
        "",
        f"Total public tools: {len(rows)}.",
        "",
        (
            "| Tool | Profile(s) | Read-Only | Destructive | Open-World | Idempotent | "
            "Headless | Requires KiCad Running | Summary |"
        ),
        "|---|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in rows:
        profiles = ", ".join(row.profiles)
        lines.append(
            "| "
            f"`{row.name}` | {profiles} | {_yes(row.read_only)} | {_yes(row.destructive)} | "
            f"{_yes(row.open_world)} | {_yes(row.idempotent)} | {_yes(row.headless)} | "
            f"{_yes(row.requires_kicad_running)} | {row.summary} |"
        )

    lines.extend(["", "### Per-Tool Annotation Notes", ""])
    for row in rows:
        flags = [
            f"profiles={', '.join(row.profiles)}",
            f"readOnly={_yes(row.read_only)}",
            f"destructive={_yes(row.destructive)}",
            f"openWorld={_yes(row.open_world)}",
            f"idempotent={_yes(row.idempotent)}",
            f"headless={_yes(row.headless)}",
            f"requiresKiCadRunning={_yes(row.requires_kicad_running)}",
        ]
        lines.append(f"- `{row.name}`: {'; '.join(flags)}.")

    return "\n".join(lines) + "\n"


def render_doc(generated: str) -> str:
    current = DOC_PATH.read_text(encoding="utf-8")
    section = f"{SECTION_HEADING}\n\n{generated}"
    if SECTION_HEADING in current:
        prefix = current.split(SECTION_HEADING, 1)[0].rstrip()
        return f"{prefix}\n\n{section}"
    return f"{current.rstrip()}\n\n{section}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Refresh the complete MCP tool catalog.")
    parser.add_argument("--check", action="store_true", help="Fail if committed docs are stale.")
    args = parser.parse_args(argv)

    generated = render_generated(collect_rows())
    rendered_doc = render_doc(generated)

    generated_drift = (
        not GENERATED_PATH.is_file() or GENERATED_PATH.read_text(encoding="utf-8") != generated
    )
    doc_drift = DOC_PATH.read_text(encoding="utf-8") != rendered_doc

    if args.check:
        if generated_drift or doc_drift:
            print("tools reference drift detected", file=sys.stderr)
            print("Run: pnpm run docs:tools", file=sys.stderr)
            return 1
        print("tools reference OK")
        return 0

    GENERATED_PATH.write_text(generated, encoding="utf-8", newline="\n")
    DOC_PATH.write_text(rendered_doc, encoding="utf-8", newline="\n")
    print(f"wrote {GENERATED_PATH.relative_to(ROOT)}")
    print(f"updated {DOC_PATH.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
