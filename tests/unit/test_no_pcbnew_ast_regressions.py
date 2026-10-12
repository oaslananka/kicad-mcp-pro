"""Guard against changing the emitted AST import/attribute diagnostics."""

from pathlib import Path

from scripts import check_no_pcbnew


def test_multiple_pcbnew_aliases_preserve_all_diagnostics(tmp_path: Path) -> None:
    source = tmp_path / "pcbnew_fixture.py"
    source.write_text(
        "import pcbnew, pcbnew.helpers, other_package\n"
        "from pcbnew import LoadBoard\n"
        "pcbnew.LoadBoard('x')\n",
        encoding="utf-8",
    )
    assert check_no_pcbnew._violations(source) == [
        f"{source}:1: deprecated pcbnew import",
        f"{source}:1: deprecated pcbnew import",
        f"{source}:2: deprecated pcbnew import",
        f"{source}:3: deprecated pcbnew attribute access",
    ]


def test_invalid_python_reports_existing_parse_diagnostic(tmp_path: Path) -> None:
    source = tmp_path / "broken.py"
    source.write_text("def broken(:\n", encoding="utf-8")
    findings = check_no_pcbnew._violations(source)
    assert len(findings) == 1
    assert findings[0].startswith(f"{source}: cannot parse Python file:")
