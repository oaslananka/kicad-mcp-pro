"""Sonar Cobertura source identity regression cases; never invent line hits."""

from __future__ import annotations

import sys
from html import escape
from pathlib import Path

import pytest
from defusedxml import ElementTree

from scripts import normalize_sonar_coverage as normalizer
from scripts.normalize_sonar_coverage import normalize


def _write_coverage(
    root: Path,
    classes: list[tuple[str, list[tuple[int, int]]]],
    sources: list[Path],
) -> Path:
    parts = ['<coverage lines-covered="4" lines-valid="4" line-rate="1"><sources>']
    for path in sources:
        parts.append(f"<source>{escape(str(path))}</source>")
    parts.append('</sources><packages><package name="fixture"><classes>')
    for name, hits in classes:
        parts.append(f'<class filename="{escape(name, quote=True)}"><lines>')
        for number, hit_count in hits:
            parts.append(f'<line number="{number}" hits="{hit_count}" />')
        parts.append("</lines></class>")
    parts.append("</classes></package></packages></coverage>")
    filename = root / "coverage.xml"
    filename.write_text("".join(parts), encoding="utf-8")
    return filename


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    src = tmp_path / "src" / "kicad_mcp"
    plugin = tmp_path / "packages" / "kicad-plugin"
    src.mkdir(parents=True)
    plugin.mkdir(parents=True)
    (src / "__init__.py").write_text(
        '"""package"""\n\n'
        "from __future__ import annotations\n\n"
        '__all__ = ["__version__"]\n\n'
        '__version__ = "4.21.1"\n',
        encoding="utf-8",
    )
    (plugin / "__init__.py").write_text('"""KiCad companion"""\n', encoding="utf-8")
    (plugin / "plugin.py").write_text('"""plugin"""\n\nvalue = 1\n', encoding="utf-8")
    return tmp_path, src, plugin


def test_ambiguous_basename_resolved_without_changing_coverage_hits(tmp_path: Path) -> None:
    root, src, plugin = _fixture(tmp_path)
    input_path = _write_coverage(
        root,
        [
            ("__init__.py", [(3, 1), (5, 1), (7, 1)]),
            ("plugin.py", [(1, 1), (3, 0)]),
        ],
        [plugin, src],
    )
    original = input_path.read_bytes()
    output = root / "coverage-sonar.xml"

    assert normalize(root, input_path, output) == 2
    assert input_path.read_bytes() == original

    doc = ElementTree.parse(output).getroot()
    assert doc.attrib["lines-covered"] == "4"
    assert doc.attrib["line-rate"] == "1"
    assert [s.text for s in doc.findall("./sources/source")] == [str(root)]
    classes = doc.findall("./packages/package/classes/class")
    assert [item.attrib["filename"] for item in classes] == [
        "src/kicad_mcp/__init__.py",
        "packages/kicad-plugin/plugin.py",
    ]
    assert [
        [(line.attrib["number"], line.attrib["hits"]) for line in cl.findall("./lines/line")]
        for cl in classes
    ] == [[("3", "1"), ("5", "1"), ("7", "1")], [("1", "1"), ("3", "0")]]


def test_ambiguous_paths_fail_closed_instead_of_assigning_fake_hits(tmp_path: Path) -> None:
    root, src, plugin = _fixture(tmp_path)
    (plugin / "__init__.py").write_text("\n".join(["x = 0"] * 8), encoding="utf-8")
    source = _write_coverage(root, [("__init__.py", [(3, 1), (7, 1)])], [plugin, src])
    output = root / "coverage-sonar.xml"

    with pytest.raises(ValueError, match="uniquely resolved"):
        normalize(root, source, output)
    assert not output.exists()


@pytest.mark.parametrize(
    "filename",
    ("../outside.py", "/etc/passwd.py", "nonexistent.py", "module.txt"),
)
def test_invalid_or_unmatched_paths_are_not_dropped(tmp_path: Path, filename: str) -> None:
    root, src, plugin = _fixture(tmp_path)
    source = _write_coverage(root, [(filename, [(1, 1)])], [src, plugin])
    with pytest.raises(ValueError, match="unsafe|uniquely"):
        normalize(root, source, root / "coverage-sonar.xml")


def test_out_of_repo_source_and_signed_input_rejected(tmp_path: Path) -> None:
    root, src, plugin = _fixture(tmp_path)
    other = tmp_path.parent / "outside-coverage-root"
    other.mkdir(exist_ok=True)
    source = _write_coverage(root, [("__init__.py", [(3, 1)])], [other])
    with pytest.raises(ValueError, match="outside"):
        normalize(root, source, root / "coverage-sonar.xml")
    source = _write_coverage(root, [("__init__.py", [(3, 1)])], [src, plugin])
    with pytest.raises(ValueError, match="signed coverage input"):
        normalize(root, source, source)


def test_empty_coverage_class_with_unique_source_is_preserved(tmp_path: Path) -> None:
    root, src, plugin = _fixture(tmp_path)
    output = root / "coverage-sonar.xml"
    source = _write_coverage(root, [("plugin.py", [])], [plugin, src])
    assert normalize(root, source, output) == 1
    klass = ElementTree.parse(output).getroot().find("./packages/package/classes/class")
    assert klass is not None
    assert klass.attrib["filename"] == "packages/kicad-plugin/plugin.py"
    assert klass.findall("./lines/line") == []


def test_xml_entities_are_rejected_without_producing_coverage(tmp_path: Path) -> None:
    root, _, _ = _fixture(tmp_path)
    source = root / "coverage.xml"
    source.write_bytes(
        b'<!DOCTYPE coverage [<!ENTITY injected "unsafe">]><coverage>&injected;</coverage>'
    )
    with pytest.raises(ElementTree.EntitiesForbidden):
        normalize(root, source, root / "coverage-sonar.xml")
    assert not (root / "coverage-sonar.xml").exists()


def test_cli_rejects_caller_selected_source_or_output_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, src, plugin = _fixture(tmp_path)
    source = _write_coverage(root, [("__init__.py", [(3, 1), (7, 1)])], [src, plugin])
    before = source.read_bytes()
    monkeypatch.setattr(normalizer, "_REPO_ROOT", root)
    monkeypatch.setattr(
        sys, "argv", ["normalize_sonar_coverage.py", "--input", str(root / "other.xml")]
    )
    with pytest.raises(SystemExit, match="does not accept"):
        normalizer.main()
    assert source.read_bytes() == before
    assert not (root / "coverage-sonar.xml").exists()


def test_ci_entrypoint_uses_only_fixed_repo_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root, src, plugin = _fixture(tmp_path)
    source = _write_coverage(root, [("__init__.py", [(3, 1), (7, 1)])], [src, plugin])
    before = source.read_bytes()
    monkeypatch.setattr(normalizer, "_REPO_ROOT", root)
    monkeypatch.setattr(sys, "argv", ["normalize_sonar_coverage.py"])
    normalizer.main()
    assert source.read_bytes() == before
    result = ElementTree.parse(root / "coverage-sonar.xml").getroot()
    klass = result.find("./packages/package/classes/class")
    assert klass is not None
    assert klass.attrib["filename"] == "src/kicad_mcp/__init__.py"
    assert "source paths resolved: 1" in capsys.readouterr().out
