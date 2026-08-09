from __future__ import annotations

import json
from pathlib import Path

import pytest

from kicad_mcp.export.board_stats import ExportBoardStatsService


class FakeCli:
    def __init__(self, result: tuple[int, str, str] = (0, "", "")) -> None:
        self.result = result
        self.calls: list[list[list[str]]] = []

    def __call__(self, variants: list[list[str]]) -> tuple[int, str, str]:
        self.calls.append(variants)
        return self.result


def _output_dir(root: Path, subdir: str | None = None) -> Path:
    target = root if not subdir else root / subdir
    target.mkdir(parents=True, exist_ok=True)
    return target


def test_get_board_stats_preserves_preview_and_cli_variants(tmp_path: Path) -> None:
    board = tmp_path / "demo.kicad_pcb"
    output = tmp_path / "output"
    output.mkdir()
    (output / "board_stats.txt").write_text("raw stats", encoding="utf-8")
    cli = FakeCli()
    service = ExportBoardStatsService(
        get_pcb_file=lambda: board,
        ensure_output_dir=lambda subdir=None: _output_dir(output, subdir),
        run_cli_variants=cli,
        read_preview=lambda path: f"preview:{path.read_text(encoding='utf-8')}",
    )

    assert service.get_board_stats() == "preview:raw stats"
    assert cli.calls == [
        [
            ["pcb", "export", "stats", "--output", str(output / "board_stats.txt"), str(board)],
            [
                "pcb",
                "export",
                "stats",
                "--input",
                str(board),
                "--output",
                str(output / "board_stats.txt"),
            ],
        ]
    ]


def test_export_board_stats_preserves_json_output_and_path_validation(tmp_path: Path) -> None:
    board = tmp_path / "demo.kicad_pcb"
    output = tmp_path / "output"
    stats_dir = output / "stats"
    stats_dir.mkdir(parents=True)
    (stats_dir / "board_stats.json").write_text('{"nets": 3}', encoding="utf-8")
    cli = FakeCli()
    service = ExportBoardStatsService(
        get_pcb_file=lambda: board,
        ensure_output_dir=lambda subdir=None: _output_dir(output, subdir),
        run_cli_variants=cli,
        read_preview=lambda path: path.read_text(encoding="utf-8"),
    )

    assert service.export_board_stats() == json.dumps({"nets": 3}, indent=2)
    assert cli.calls[0][0] == [
        "pcb",
        "export",
        "stats",
        "--output",
        str(stats_dir / "board_stats.json"),
        str(board),
    ]
    with pytest.raises(ValueError, match="single file name"):
        service.export_board_stats("nested/stats.json")
