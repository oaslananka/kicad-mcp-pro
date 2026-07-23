from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from kicad_mcp.models.tool_result import MutatingToolResult, TransactionVerification
from kicad_mcp.schematic.document_settings import SchematicDocumentSettingsService


@dataclass(frozen=True)
class FakeTarget:
    path: Path
    is_root: bool = True
    description: str = "root"


PAPER_SIZES = {
    "A4": (297.0, 210.0),
    "A3": (420.0, 297.0),
    "A2": (594.0, 420.0),
    "A1": (841.0, 594.0),
    "A0": (1189.0, 841.0),
    "B": (431.8, 279.4),
    "C": (558.8, 431.8),
    "D": (863.6, 558.8),
    "E": (1117.6, 863.6),
}


def _paper_from_file(path: Path) -> str:
    match = re.search(r'\(paper\s+"([^"]+)"', path.read_text(encoding="utf-8"))
    return match.group(1) if match else "A4"


def _service(
    path: Path,
    *,
    parse_schematic: Callable[[Path], dict[str, Any]] | None = None,
    transactional_write: Callable[[Callable[[str], str], Path], None] | None = None,
    reload_schematic: Callable[[], str] | None = None,
    resolve_target: Callable[..., FakeTarget] | None = None,
    apply_title_block_updates: Callable[[str, dict[str, str]], str] | None = None,
    sheet_usable_cols: Callable[[str], int] | None = None,
    sheet_usable_rows: Callable[[str], int] | None = None,
) -> SchematicDocumentSettingsService:
    def write(mutator: Callable[[str], str], target: Path) -> None:
        current = target.read_text(encoding="utf-8")
        target.write_text(mutator(current), encoding="utf-8")

    def default_resolve(
        *,
        sheet: str | None = None,
        sheet_file: str | None = None,
    ) -> FakeTarget:
        _ = (sheet, sheet_file)
        return FakeTarget(path)

    return SchematicDocumentSettingsService(
        active_schematic_file=lambda: path,
        resolve_target=resolve_target or default_resolve,
        parse_schematic=parse_schematic or (lambda _path: {"symbols": [], "power_symbols": []}),
        apply_title_block_updates=apply_title_block_updates
        or (
            lambda current, updates: (
                current + "|" + ",".join(f"{k}={v}" for k, v in updates.items())
            )
        ),
        transactional_write=transactional_write or write,
        reload_schematic=reload_schematic or (lambda: "Reloaded."),
        format_target_detail=lambda target: (
            f"Target schematic ({'root' if target.is_root else 'child'}): {target.path}"
        ),
        read_sheet_paper=_paper_from_file,
        sheet_usable_cols=sheet_usable_cols or (lambda _paper: 9),
        sheet_usable_rows=sheet_usable_rows or (lambda _paper: 7),
        paper_sizes_mm=PAPER_SIZES,
        layout_origin_x_mm=25.4,
        sheet_margin_mm=12.7,
        symbol_half_width_mm=10.0,
        symbol_half_height_mm=8.0,
    )


def test_title_block_requires_at_least_one_field(tmp_path: Path) -> None:
    path = tmp_path / "root.kicad_sch"
    path.write_text("root", encoding="utf-8")
    resolved = False

    def resolve(**_: object) -> FakeTarget:
        nonlocal resolved
        resolved = True
        return FakeTarget(path)

    result = _service(path, resolve_target=resolve).set_title_block_info(
        None, None, None, None, None, None, None, None, None, None, False
    )

    assert result == "No schematic title block fields specified. Provide at least one field."
    assert resolved is False


def test_title_block_dry_run_preserves_order_hashes_and_target(tmp_path: Path) -> None:
    path = tmp_path / "child.kicad_sch"
    before = "(kicad_sch)"
    path.write_text(before, encoding="utf-8")
    target_calls: list[tuple[str | None, str | None]] = []
    writes: list[Path] = []
    reloads = 0

    def resolve(*, sheet: str | None = None, sheet_file: str | None = None) -> FakeTarget:
        target_calls.append((sheet, sheet_file))
        return FakeTarget(path, is_root=False, description="child")

    def update(current: str, updates: dict[str, str]) -> str:
        assert list(updates) == ["title", "rev", "company", "comment2"]
        return current + "|" + ",".join(f"{key}={value}" for key, value in updates.items())

    def write(_mutator: Callable[[str], str], target: Path) -> None:
        writes.append(target)

    def reload() -> str:
        nonlocal reloads
        reloads += 1
        return "Reloaded."

    service = _service(
        path,
        resolve_target=resolve,
        apply_title_block_updates=update,
        transactional_write=write,
        reload_schematic=reload,
    )
    result = service.set_title_block_info(
        "power",
        None,
        "Power",
        "B",
        None,
        "Acme",
        None,
        "Reviewed",
        None,
        None,
        True,
    )

    planned = "(kicad_sch)|title=Power,rev=B,company=Acme,comment2=Reviewed"
    expected = MutatingToolResult(
        changed_files=[str(path)],
        changed_objects=[
            "title_block.title",
            "title_block.rev",
            "title_block.company",
            "title_block.comment2",
        ],
        before_hash=hashlib.sha256(before.encode()).hexdigest(),
        after_hash=hashlib.sha256(planned.encode()).hexdigest(),
        verification=TransactionVerification(roundtrip="planned_not_written"),
        dry_run=True,
    ).to_compat_text(
        "Dry run: schematic title block fields would be updated: title, rev, company, comment2."
    )
    assert result == expected
    assert target_calls == [("power", None)]
    assert writes == []
    assert reloads == 0
    assert path.read_text(encoding="utf-8") == before


def test_title_block_commit_preserves_write_reload_and_transaction_text(tmp_path: Path) -> None:
    path = tmp_path / "root.kicad_sch"
    before = "(kicad_sch)"
    path.write_text(before, encoding="utf-8")
    events: list[str] = []

    def write(mutator: Callable[[str], str], target: Path) -> None:
        events.append("write")
        target.write_text(mutator(target.read_text(encoding="utf-8")), encoding="utf-8")

    def reload() -> str:
        events.append("reload")
        return "The schematic was reloaded."

    service = _service(path, transactional_write=write, reload_schematic=reload)
    result = service.set_title_block_info(
        None,
        "root.kicad_sch",
        "Main",
        None,
        "2026-07-23",
        None,
        "Approved",
        None,
        None,
        None,
        False,
    )

    after = "(kicad_sch)|title=Main,date=2026-07-23,comment1=Approved"
    expected = MutatingToolResult(
        changed_files=[str(path)],
        changed_objects=["title_block.title", "title_block.date", "title_block.comment1"],
        before_hash=hashlib.sha256(before.encode()).hexdigest(),
        after_hash=hashlib.sha256(after.encode()).hexdigest(),
        verification=TransactionVerification(roundtrip="validated"),
    ).to_compat_text(
        f"The schematic was reloaded.\nTarget schematic (root): {path}\n"
        "Updated schematic title block fields: title, date, comment1."
    )
    assert result == expected
    assert events == ["write", "reload"]
    assert path.read_text(encoding="utf-8") == after


def test_set_sheet_size_rejects_unknown_paper_after_trimming(tmp_path: Path) -> None:
    path = tmp_path / "root.kicad_sch"
    path.write_text('(kicad_sch\n  (paper "A4")\n)', encoding="utf-8")

    result = _service(path).set_sheet_size(" BAD ")

    assert result == "Unknown paper size 'BAD'. Available sizes: A0, A1, A2, A3, A4, B, C, D, E."


def test_set_sheet_size_replaces_paper_and_preserves_summary(tmp_path: Path) -> None:
    path = tmp_path / "root.kicad_sch"
    path.write_text('(kicad_sch\n  (paper "A4")\n)', encoding="utf-8")
    calls: list[str] = []

    service = _service(
        path,
        reload_schematic=lambda: calls.append("reload") or "Reloaded.",
        sheet_usable_cols=lambda paper: calls.append(f"cols:{paper}") or 14,
        sheet_usable_rows=lambda paper: calls.append(f"rows:{paper}") or 11,
    )
    result = service.set_sheet_size(" A3 ")

    assert '(paper "A3")' in path.read_text(encoding="utf-8")
    assert calls == ["reload", "cols:A3", "rows:A3"]
    assert result == (
        "Reloaded.\n"
        "Sheet resized: A4 (297x210 mm) -> A3 (420x297 mm).\n"
        "Usable grid: 14 columns x 11 rows (origin 25.4 mm, margin 12.7 mm).\n"
        "Tip: run sch_auto_place_functional to redistribute symbols on the new sheet."
    )


def test_set_sheet_size_inserts_missing_declaration(tmp_path: Path) -> None:
    path = tmp_path / "root.kicad_sch"
    path.write_text("(kicad_sch\n  (version 20231120)\n)", encoding="utf-8")

    result = _service(path).set_sheet_size("A3")

    assert path.read_text(encoding="utf-8").startswith('(kicad_sch\n  (paper "A3")\n')
    assert "Sheet resized: A4 (297x210 mm) -> A3 (420x297 mm)." in result


def test_set_sheet_size_reports_already_set_without_reload(tmp_path: Path) -> None:
    path = tmp_path / "root.kicad_sch"
    original = '(kicad_sch\n  (paper "A3")\n)'
    path.write_text(original, encoding="utf-8")
    reloads = 0

    def reload() -> str:
        nonlocal reloads
        reloads += 1
        return "Reloaded."

    result = _service(path, reload_schematic=reload).set_sheet_size("A3")

    assert result == "Sheet is already 'A3' (420 x 297 mm). No change made."
    assert reloads == 0
    assert path.read_text(encoding="utf-8") == original


def test_set_sheet_size_preserves_write_failure_text(tmp_path: Path) -> None:
    path = tmp_path / "root.kicad_sch"
    path.write_text('(kicad_sch\n  (paper "A4")\n)', encoding="utf-8")

    def fail(_mutator: Callable[[str], str], _target: Path) -> None:
        raise OSError("disk full")

    assert _service(path, transactional_write=fail).set_sheet_size("A3") == (
        "Could not write schematic file: disk full"
    )


def test_auto_resize_handles_empty_and_oversized_schematics(tmp_path: Path) -> None:
    path = tmp_path / "root.kicad_sch"
    path.write_text('(kicad_sch\n  (paper "A4")\n)', encoding="utf-8")

    empty = _service(path).auto_resize_sheet()
    huge = _service(
        path,
        parse_schematic=lambda _path: {
            "symbols": [{"x": 2000.0, "y": 1000.0}],
            "power_symbols": [],
        },
    ).auto_resize_sheet()

    assert empty == "No symbols found — sheet size unchanged."
    assert huge == (
        "Symbols span 2023 x 1021 mm — no standard size is large enough.  "
        "Consider splitting into hierarchical sheets (sch_create_sheet)."
    )


def test_auto_resize_reports_current_sheet_when_it_already_fits(tmp_path: Path) -> None:
    path = tmp_path / "root.kicad_sch"
    path.write_text('(kicad_sch\n  (paper "A4")\n)', encoding="utf-8")
    service = _service(
        path,
        parse_schematic=lambda _path: {
            "symbols": [{"x": 100.0, "y": 80.0}],
            "power_symbols": [{"x_mm": 120.0, "y_mm": 90.0}],
        },
    )

    assert service.auto_resize_sheet() == (
        "Current sheet 'A4' (297x210 mm) already fits all symbols (required 143x111 mm)."
    )


def test_auto_resize_delegates_to_explicit_resize_for_first_fitting_size(tmp_path: Path) -> None:
    path = tmp_path / "root.kicad_sch"
    path.write_text('(kicad_sch\n  (paper "A4")\n)', encoding="utf-8")
    service = _service(
        path,
        parse_schematic=lambda _path: {
            "symbols": [{"x": 330.0, "y": 170.0}],
            "power_symbols": [],
        },
    )

    result = service.auto_resize_sheet()

    assert '(paper "A3")' in path.read_text(encoding="utf-8")
    assert "Sheet resized: A4 (297x210 mm) -> A3 (420x297 mm)." in result
