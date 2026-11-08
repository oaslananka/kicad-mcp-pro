"""Coverage evidence must be same-run, complete and source-path bounded."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from coverage import CoverageData

from scripts import merge_platform_coverage as combine

_SHA = "a" * 40
_RUN = 123


@pytest.fixture
def platform_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    source = tmp_path / "src" / "kicad_mcp" / "test_module.py"
    source.parent.mkdir(parents=True)
    source.write_text("first = 1\nsecond = 2\n", encoding="utf-8")
    data = CoverageData(basename=str(tmp_path / ".coverage"))
    data.add_lines({str(source.resolve()): {1}})
    data.write()
    (tmp_path / "windows-coverage.json").write_text(
        json.dumps(
            {
                "files": {
                    "src\\kicad_mcp\\test_module.py": {
                        "executed_lines": [2],
                        "missing_lines": [1],
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    def same_commit(_root: Path, sha: str) -> None:
        assert sha == _SHA

    monkeypatch.setattr(combine, "_source_sha", same_commit)
    return tmp_path


def test_native_coverage_merges_executed_lines_and_regenerates_both_formats(
    platform_data: Path,
) -> None:
    combine.stamp_windows_report(platform_data, _SHA, _RUN, 1)
    assert combine.merge_native_coverage(platform_data, _SHA, _RUN, 1) == 1

    data = CoverageData(basename=str(platform_data / ".coverage"))
    data.read()
    source = (platform_data / "src" / "kicad_mcp" / "test_module.py").resolve()
    assert set(data.lines(str(source)) or ()) == {1, 2}
    merged = json.loads((platform_data / "coverage.json").read_text(encoding="utf-8"))
    assert any(sorted(f["executed_lines"]) == [1, 2] for f in merged["files"].values())
    assert (platform_data / "coverage.xml").is_file()


def test_native_coverage_rejects_other_run_or_tampered_bytes(
    platform_data: Path,
) -> None:
    combine.stamp_windows_report(platform_data, _SHA, _RUN, 1)
    with pytest.raises(ValueError, match="stale|cross-run"):
        combine.merge_native_coverage(platform_data, _SHA, _RUN + 1, 1)
    with pytest.raises(ValueError, match="stale|cross-run"):
        combine.merge_native_coverage(platform_data, _SHA, _RUN, 2)
    report = platform_data / "windows-coverage.json"
    report.write_text(report.read_text("utf-8") + " ", encoding="utf-8")
    with pytest.raises(ValueError, match="stale|altered"):
        combine.merge_native_coverage(platform_data, _SHA, _RUN, 1)
    assert not (platform_data / "coverage.xml").exists()


@pytest.mark.parametrize(
    ("source_path", "executed"),
    [
        ("../secrets.py", [1]),
        ("/outside.py", [1]),
        ("src/kicad_mcp/test_module.py", [True]),
        ("src/kicad_mcp/test_module.py", [10000]),
        ("src/kicad_mcp/test_module.py", "2"),
    ],
)
def test_native_coverage_rejects_untrusted_paths_and_invalid_hits(
    platform_data: Path, source_path: str, executed: object
) -> None:
    (platform_data / "windows-coverage.json").write_text(
        json.dumps({"files": {source_path: {"executed_lines": executed}}}), encoding="utf-8"
    )
    combine.stamp_windows_report(platform_data, _SHA, _RUN, 1)
    with pytest.raises(ValueError, match="unsafe|Invalid|escaped|non-package"):
        combine.merge_native_coverage(platform_data, _SHA, _RUN, 1)
    assert not (platform_data / "coverage.xml").exists()


def test_native_coverage_requires_both_reports_and_compatible_modes(
    platform_data: Path,
) -> None:
    combine.stamp_windows_report(platform_data, _SHA, _RUN, 1)
    (platform_data / ".coverage").unlink()
    with pytest.raises(ValueError, match="Missing Linux"):
        combine.merge_native_coverage(platform_data, _SHA, _RUN, 1)


def test_native_coverage_rejects_missing_manifest(
    platform_data: Path,
) -> None:
    with pytest.raises(ValueError, match="Missing or unsafe"):
        combine.merge_native_coverage(platform_data, _SHA, _RUN, 1)
