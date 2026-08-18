from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
WRITER_FILES = (
    "src/kicad_mcp/library/local_authoring.py",
    "src/kicad_mcp/schematic/circuit_compilation.py",
    "src/kicad_mcp/tools/board_file.py",
    "src/kicad_mcp/tools/pcb.py",
    "src/kicad_mcp/tools/project.py",
    "src/kicad_mcp/utils/footprint_gen.py",
    "src/kicad_mcp/utils/symbol_gen.py",
)


def test_generated_writers_do_not_embed_numeric_format_versions() -> None:
    offenders: list[str] = []
    for relative in WRITER_FILES:
        text = (REPO_ROOT / relative).read_text(encoding="utf-8")
        for version in ("20250216", "20250316"):
            if version in text:
                offenders.append(f"{relative}: {version}")

    assert offenders == [], "Move writer format versions behind the shared format contract"


def test_generated_format_migrator_upgrades_in_place_formats(tmp_path: Path) -> None:
    import kicad_mcp.file_formats as formats

    migrate = getattr(formats, "upgrade_generated_file", None)
    assert migrate is not None, "Format contract must expose a generated-file migrator"

    calls: list[tuple[str, ...]] = []

    def run_cli(*args: str) -> tuple[int, str, str]:
        calls.append(args)
        return 0, "saved", ""

    for kind, suffix in (("pcb", ".kicad_pcb"), ("sch", ".kicad_sch"), ("sym", ".kicad_sym")):
        path = tmp_path / f"demo{suffix}"
        path.write_text("legacy", encoding="utf-8")
        result = migrate(path, kind, run_cli)
        assert result.upgraded is True

    assert calls == [
        ("pcb", "upgrade", "--force", str(tmp_path / "demo.kicad_pcb")),
        ("sch", "upgrade", "--force", str(tmp_path / "demo.kicad_sch")),
        ("sym", "upgrade", "--force", str(tmp_path / "demo.kicad_sym")),
    ]


def test_generated_format_migrator_preserves_footprint_name(tmp_path: Path) -> None:
    import kicad_mcp.file_formats as formats

    migrate = getattr(formats, "upgrade_generated_file", None)
    assert migrate is not None, "Format contract must expose a generated-file migrator"

    target = tmp_path / "custom-output-name.kicad_mod"
    target.write_text(
        '(footprint "C_0603"\n\t(version 20250316)\n\t(generator "kicad-mcp")\n)\n',
        encoding="utf-8",
    )

    def run_cli(*args: str) -> tuple[int, str, str]:
        assert args[:4] == ("fp", "upgrade", "--force", "--output")
        output_dir = Path(args[4])
        input_dir = Path(args[5])
        input_file = input_dir / "C_0603.kicad_mod"
        assert input_file.is_file()
        output_dir.mkdir(parents=True)
        (output_dir / input_file.name).write_text(
            '(footprint "C_0603"\n\t(version 20260206)\n\t(generator "pcbnew")\n)\n',
            encoding="utf-8",
        )
        return 0, "", ""

    result = migrate(target, "fp", run_cli)

    assert result.upgraded is True
    assert '(footprint "C_0603"' in target.read_text(encoding="utf-8")
    assert "20260206" in target.read_text(encoding="utf-8")


def test_generated_format_migrator_keeps_writer_dialect_when_cli_is_unavailable(
    tmp_path: Path,
) -> None:
    from kicad_mcp.file_formats import upgrade_generated_file

    target = tmp_path / "demo.kicad_sch"
    original = "(kicad_sch\n\t(version 20250316)\n)\n"
    target.write_text(original, encoding="utf-8")

    def run_cli(*_args: str) -> tuple[int, str, str]:
        raise FileNotFoundError("kicad-cli missing")

    result = upgrade_generated_file(target, "sch", run_cli)

    assert result.upgraded is False
    assert "kicad-cli missing" in result.detail
    assert target.read_text(encoding="utf-8") == original


def test_generated_format_migrator_restores_original_file_on_failed_in_place_upgrade(
    tmp_path: Path,
) -> None:
    from kicad_mcp.file_formats import upgrade_generated_file

    target = tmp_path / "demo.kicad_pcb"
    original = '(kicad_pcb (version 20250316) (generator "kicad-mcp-pro"))\n'
    target.write_text(original, encoding="utf-8")

    def run_cli(*_args: str) -> tuple[int, str, str]:
        target.write_text("partially rewritten", encoding="utf-8")
        return 1, "", "conversion failed"

    result = upgrade_generated_file(target, "pcb", run_cli)

    assert result.upgraded is False
    assert result.detail == "conversion failed"
    assert target.read_text(encoding="utf-8") == original
