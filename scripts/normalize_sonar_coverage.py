"""Map coverage.py's multi-source XML paths to unique repository-relative paths.

Sonar cannot resolve a Cobertura class like "__init__.py" when multiple
<source> roots contain that basename. This fixes *path identity*, not test
coverage: line-hit counts and the provenance-verified coverage.xml stay intact.
Ambiguous or missing files are errors, never silently dropped.
"""

from __future__ import annotations

import argparse
import xml.etree.ElementTree as ET
from pathlib import Path, PurePosixPath

_MAX_REPORT_BYTES = 32 * 1024 * 1024


def _safe_report(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise ValueError("Input coverage report must be a regular file")
    size = path.stat().st_size
    if size <= 0 or size > _MAX_REPORT_BYTES:
        raise ValueError("Input coverage report has invalid size")
    return path.read_bytes()


def _source_dirs(root: Path, tree: ET.Element) -> list[Path]:
    source_nodes = tree.findall("./sources/source")
    if not source_nodes:
        raise ValueError("Coverage report is missing source directories")

    dirs: list[Path] = []
    for node in source_nodes:
        raw = (node.text or "").strip()
        if not raw:
            raise ValueError("Empty coverage source directory")
        source = Path(raw)
        if not source.is_absolute():
            source = root / source
        if source.is_symlink() or not source.is_dir():
            raise ValueError("Coverage source directory does not exist")
        resolved = source.resolve()
        if not resolved.is_relative_to(root):
            raise ValueError("Coverage source is outside the repository")
        if resolved not in dirs:
            dirs.append(resolved)
    return dirs


def _validated_filename(raw: str) -> PurePosixPath:
    value = raw.replace("\\", "/")
    path = PurePosixPath(value)
    if (
        not value
        or path.is_absolute()
        or any(piece in ("", ".", "..") for piece in value.split("/"))
        or path.suffix != ".py"
    ):
        raise ValueError("Coverage entry has an unsafe source path")
    return path


def _source_for_class(root: Path, directories: list[Path], klass: ET.Element) -> str:
    path = _validated_filename(klass.attrib.get("filename", ""))
    line_elements = klass.findall("./lines/line")
    try:
        numbered_lines = [int(line.attrib["number"]) for line in line_elements]
        if any(number <= 0 for number in numbered_lines):
            raise ValueError("Invalid coverage line number")
        if any(int(line.attrib["hits"]) < 0 for line in line_elements):
            raise ValueError("Invalid coverage hit count")
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"Coverage entry has invalid line evidence: {path}") from exc

    # coverage.py emits empty classes for modules without executable lines.
    max_line = max(numbered_lines, default=0)
    candidates: set[Path] = set()
    for source_dir in directories:
        candidate = source_dir.joinpath(*path.parts)
        # No arbitrary traversal, symlinked source aliases or missing paths.
        if candidate.is_symlink() or not candidate.is_file():
            continue
        resolved = candidate.resolve()
        if not resolved.is_relative_to(root):
            continue
        if max_line <= len(candidate.read_text(encoding="utf-8").splitlines()):
            candidates.add(resolved)

    if len(candidates) != 1:
        raise ValueError(f"Coverage path cannot be uniquely resolved: {path}")
    return next(iter(candidates)).relative_to(root).as_posix()


def normalize(root: Path, report: Path, output: Path) -> int:
    """Rewrite file identities only; the original verified report is never mutated."""
    root = root.resolve(strict=True)
    if report.resolve() == output.resolve():
        raise ValueError("Refusing to overwrite the signed coverage input")
    if output.is_symlink():
        raise ValueError("Refusing to write coverage through a symlink")

    # Inputs are exact-run SHA-verified CI artifacts or locally generated test
    # reports, with bounded size; the stdlib parser does not fetch external DTDs.
    tree = ET.fromstring(_safe_report(report))  # noqa: S314
    if tree.tag != "coverage":
        raise ValueError("Expected a Cobertura XML coverage report")
    dirs = _source_dirs(root, tree)
    classes = tree.findall("./packages/package/classes/class")
    if not classes:
        raise ValueError("Coverage report has no measured source files")

    seen: set[str] = set()
    for klass in classes:
        canonical = _source_for_class(root, dirs, klass)
        if canonical in seen:
            raise ValueError(f"Duplicate coverage source file: {canonical}")
        seen.add(canonical)
        klass.set("filename", canonical)

    sources = tree.find("./sources")
    if sources is None:
        raise ValueError("Coverage sources vanished during normalization")
    for node in list(sources):
        sources.remove(node)
    ET.SubElement(sources, "source").text = str(root)
    output.write_bytes(ET.tostring(tree, encoding="utf-8", xml_declaration=True))
    return len(seen)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("coverage.xml"))
    parser.add_argument("--output", type=Path, default=Path("coverage-sonar.xml"))
    args = parser.parse_args()
    count = normalize(Path.cwd(), args.input, args.output)
    print(f"Sonar coverage source paths resolved: {count} (hit counts unchanged)")


if __name__ == "__main__":
    main()
