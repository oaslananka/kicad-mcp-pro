"""Build the KiCad capability-parity artifacts (work order P0-T4).

Source of truth: ``docs/compatibility/capability-parity-matrix.yaml``.

Generates:
  * ``src/kicad_mcp/parity_matrix_data.py`` — embedded copy the runtime tool reads
    (no YAML dependency at runtime, mirroring ``kicad_mcp.compatibility``).
  * ``docs/compatibility/capability-parity.generated.md`` — human-readable view.

Usage:
  uv run python scripts/build_parity_matrix.py                    # write artifacts
  uv run python scripts/build_parity_matrix.py --check            # fail on drift (CI)
  uv run python scripts/build_parity_matrix.py --check-regression # fail if coverage dropped
  uv run python scripts/build_parity_matrix.py --update-baseline  # ratchet the coverage floor
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yaml

from kicad_mcp.parity import coverage_summary, opportunities

ROOT = Path(__file__).resolve().parents[1]
YAML_PATH = ROOT / "docs" / "compatibility" / "capability-parity-matrix.yaml"
PY_PATH = ROOT / "src" / "kicad_mcp" / "parity_matrix_data.py"
MD_PATH = ROOT / "docs" / "compatibility" / "capability-parity.generated.md"
BASELINE_PATH = ROOT / "docs" / "compatibility" / "capability-parity-baseline.json"
README_PATH = ROOT / "README.md"

# README badge markers — the block between them is machine-managed so the
# published coverage number can never silently go stale (work order P5-T6).
BADGE_START = "<!-- parity-coverage-badge:start -->"
BADGE_END = "<!-- parity-coverage-badge:end -->"

# Coverage below baseline by more than this (percentage points) is a regression.
# A small epsilon absorbs float-rounding noise so the gate only trips on a real drop.
REGRESSION_EPS = 0.05


def load_matrix() -> dict[str, Any]:
    return yaml.safe_load(YAML_PATH.read_text(encoding="utf-8"))


def render_python(matrix: dict[str, Any]) -> str:
    raw = json.dumps(matrix, indent=2, ensure_ascii=False)
    return (
        '"""Embedded capability-parity matrix. GENERATED — do not edit by hand.\n'
        "\n"
        "Synchronized from docs/compatibility/capability-parity-matrix.yaml by\n"
        "scripts/build_parity_matrix.py. Regenerate with:\n"
        "    uv run python scripts/build_parity_matrix.py\n"
        '"""\n'
        "\n"
        "from __future__ import annotations\n"
        "\n"
        "import json\n"
        "from typing import Any\n"
        "\n"
        '_RAW = r"""\n'
        f"{raw}\n"
        '"""\n'
        "\n"
        "CAPABILITY_PARITY_MATRIX: dict[str, Any] = json.loads(_RAW)\n"
    )


def _pct(value: float) -> str:
    return f"{value:.1f}%"


def render_markdown(matrix: dict[str, Any]) -> str:
    summary = coverage_summary(matrix)
    overall = summary["overall"]
    lines: list[str] = [
        "# KiCad Capability Parity (generated)",
        "",
        "Machine-generated from `docs/compatibility/capability-parity-matrix.yaml`. "
        "Refresh with `uv run python scripts/build_parity_matrix.py`.",
        "",
        f"KiCad baseline: `{summary['kicad_baseline']}` · Updated: {summary['updated']}",
        "",
        (
            f"**Overall: {overall['covered']} / {overall['denominator']} "
            f"programmatically-reachable capabilities driven = {_pct(overall['coverage_pct'])}** "
            f"({overall['partial']} partial, {overall['gap']} gap; "
            f"{overall['gui_only_no_api']} GUI-only with no KiCad API, excluded from the "
            "denominator)."
        ),
        "",
        "## Coverage by domain",
        "",
        "| Domain | Coverage | Covered | Partial | Gap | GUI-only (no API) |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for name, stats in summary["domains"].items():
        lines.append(
            f"| `{name}` | {_pct(stats['coverage_pct'])} | {stats['covered']} | "
            f"{stats['partial']} | {stats['gap']} | {stats['gui_only_no_api']} |"
        )
    lines.append(
        f"| **Overall** | **{_pct(overall['coverage_pct'])}** | {overall['covered']} | "
        f"{overall['partial']} | {overall['gap']} | {overall['gui_only_no_api']} |"
    )

    opps = opportunities(matrix)
    lines.extend(["", "## Closeable surface (gap, then partial)", ""])
    if opps:
        lines.append("| Domain | Capability | Status | Channel | MCP tool | Notes |")
        lines.append("|---|---|---|---|---|---|")
        for row in opps:
            tool = f"`{row['mcp_tool']}`" if row["mcp_tool"] else "—"
            notes = row["notes"].replace("|", "\\|")
            lines.append(
                f"| `{row['domain']}` | {row['capability']} | `{row['status']}` | "
                f"`{row['kicad_channel']}` | {tool} | {notes} |"
            )
    else:
        lines.append("No open gaps or partials.")

    lines.extend(["", "## Full matrix", ""])
    for name, info in matrix["domains"].items():
        lines.extend(
            [
                f"### `{name}`",
                "",
                str(info.get("description", "")),
                "",
                "| Capability | Channel | MCP tool | Status | KiCad | Notes |",
                "|---|---|---|---|---|---|",
            ]
        )
        for cap in info["capabilities"]:
            tool = f"`{cap['mcp_tool']}`" if cap["mcp_tool"] else "—"
            notes = (cap["notes"] or "").replace("|", "\\|")
            lines.append(
                f"| {cap['capability']} | `{cap['kicad_channel']}` | {tool} | "
                f"`{cap['status']}` | {cap['kicad_version_introduced']} | {notes} |"
            )
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _badge_color(pct: float) -> str:
    if pct >= 90.0:
        return "brightgreen"
    if pct >= 75.0:
        return "green"
    if pct >= 50.0:
        return "yellow"
    if pct >= 25.0:
        return "orange"
    return "red"


def render_badge_block(matrix: dict[str, Any]) -> str:
    """Render the README coverage badge block (between the marker comments)."""
    pct = coverage_summary(matrix)["overall"]["coverage_pct"]
    url = f"https://img.shields.io/badge/KiCad_programmatic_parity-{pct:.1f}%25-{_badge_color(pct)}"
    return (
        f"{BADGE_START}\n"
        f"[![KiCad programmatic parity]({url})]"
        "(docs/compatibility/capability-parity.generated.md)\n"
        f"{BADGE_END}"
    )


def splice_readme_badge(readme: str, block: str) -> str:
    """Replace the marker-delimited badge block in ``readme`` with ``block``."""
    start = readme.find(BADGE_START)
    end = readme.find(BADGE_END)
    if start == -1 or end == -1:
        raise ValueError(f"README is missing the {BADGE_START} / {BADGE_END} markers")
    return readme[:start] + block + readme[end + len(BADGE_END) :]


def render_baseline(matrix: dict[str, Any]) -> str:
    """Render the coverage-floor JSON used by the regression gate."""
    summary = coverage_summary(matrix)
    payload = {
        "_comment": (
            "Coverage floor for the parity regression gate (work order P5-T6). Raise it "
            "with: uv run python scripts/build_parity_matrix.py --update-baseline. CI fails "
            "if live coverage drops below these percentages — e.g. a KiCad update breaking a hook."
        ),
        "overall": summary["overall"]["coverage_pct"],
        "domains": {name: stats["coverage_pct"] for name, stats in summary["domains"].items()},
    }
    return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"


def check_regression(matrix: dict[str, Any]) -> list[str]:
    """Return a list of regression failures (empty == coverage held or improved)."""
    if not BASELINE_PATH.is_file():
        return [
            f"baseline missing ({BASELINE_PATH.name}): "
            "run 'build_parity_matrix.py --update-baseline'"
        ]
    baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    summary = coverage_summary(matrix)
    failures: list[str] = []

    current_overall = summary["overall"]["coverage_pct"]
    floor_overall = float(baseline.get("overall", 0.0))
    if current_overall + REGRESSION_EPS < floor_overall:
        failures.append(f"overall {current_overall:.1f}% < baseline {floor_overall:.1f}%")

    for name, floor in baseline.get("domains", {}).items():
        domain = summary["domains"].get(name)
        if domain is None:
            failures.append(
                f"domain '{name}' vanished from the matrix (baseline {float(floor):.1f}%)"
            )
            continue
        current = domain["coverage_pct"]
        if current + REGRESSION_EPS < float(floor):
            failures.append(f"domain '{name}' {current:.1f}% < baseline {float(floor):.1f}%")
    return failures


def _handle_check_regression(matrix: dict[str, Any]) -> int:
    failures = check_regression(matrix)
    if failures:
        print("capability-parity coverage REGRESSION:", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        for row in opportunities(matrix, limit=5):
            print(
                f"  open: {row['domain']}/{row['capability']} [{row['status']}]",
                file=sys.stderr,
            )
        print(
            "If this drop is intentional, justify it and run --update-baseline.",
            file=sys.stderr,
        )
        return 1
    overall = coverage_summary(matrix)["overall"]["coverage_pct"]
    print(f"capability-parity coverage OK: {overall:.1f}% (>= baseline)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the capability-parity artifacts.")
    parser.add_argument("--check", action="store_true", help="Fail if committed artifacts drift.")
    parser.add_argument(
        "--check-regression",
        action="store_true",
        help="Fail if live coverage dropped below the committed baseline (CI gate).",
    )
    parser.add_argument(
        "--update-baseline",
        action="store_true",
        help="Write the coverage floor to the baseline (ratchet after an intentional change).",
    )
    args = parser.parse_args(argv)

    matrix = load_matrix()

    if args.check_regression:
        return _handle_check_regression(matrix)

    py_text = render_python(matrix)
    md_text = render_markdown(matrix)
    badge_block = render_badge_block(matrix)
    readme_text = README_PATH.read_text(encoding="utf-8")
    readme_desired = splice_readme_badge(readme_text, badge_block)

    if args.update_baseline:
        BASELINE_PATH.write_text(render_baseline(matrix), encoding="utf-8", newline="\n")
        overall = coverage_summary(matrix)["overall"]["coverage_pct"]
        print(f"wrote {BASELINE_PATH.relative_to(ROOT)} (overall {overall:.1f}%)")
        return 0

    py_drift = not PY_PATH.is_file() or PY_PATH.read_text(encoding="utf-8") != py_text
    md_drift = not MD_PATH.is_file() or MD_PATH.read_text(encoding="utf-8") != md_text
    readme_drift = readme_text != readme_desired

    if args.check:
        drifts = ((PY_PATH, py_drift), (MD_PATH, md_drift), (README_PATH, readme_drift))
        stale = [str(path.relative_to(ROOT)) for path, drift in drifts if drift]
        if stale:
            print(f"capability-parity drift detected: {', '.join(stale)}", file=sys.stderr)
            print("Run: uv run python scripts/build_parity_matrix.py", file=sys.stderr)
            return 1
        print("capability-parity artifacts OK")
        return 0

    PY_PATH.write_text(py_text, encoding="utf-8", newline="\n")
    MD_PATH.write_text(md_text, encoding="utf-8", newline="\n")
    if readme_drift:
        README_PATH.write_text(readme_desired, encoding="utf-8", newline="\n")
        print(f"updated {README_PATH.relative_to(ROOT)} badge")
    print(f"wrote {PY_PATH.relative_to(ROOT)}")
    print(f"wrote {MD_PATH.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
