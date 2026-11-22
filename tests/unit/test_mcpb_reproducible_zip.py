"""MCPB zip metadata must be deterministic without changing member data."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from scripts.normalize_mcpb_timestamps import normalize_mcpb_timestamps

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "normalize_mcpb_timestamps.py"
_FIXED = (1980, 1, 1, 0, 0, 0)


def _normalize(path: Path) -> None:
    path.write_bytes(normalize_mcpb_timestamps(path.read_bytes()))


def _create(path: Path, stamp: tuple[int, int, int, int, int, int]) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for name, value in (
            ("manifest.json", b'{"manifest_version":"0.3","version":"4.21.6"}'),
            ("icon.png", b"\x89PNG\r\n\x1a\nfixture"),
        ):
            info = zipfile.ZipInfo(name, date_time=stamp)
            info.compress_type = zipfile.ZIP_DEFLATED
            bundle.writestr(info, value)


def test_mcpb_timestamp_normalizer_makes_identical_contents_byte_identical(tmp_path: Path) -> None:
    first, second = tmp_path / "first.mcpb", tmp_path / "second.mcpb"
    _create(first, (2026, 11, 22, 15, 11, 32))
    _create(second, (2026, 11, 22, 15, 26, 58))
    assert first.read_bytes() != second.read_bytes()

    with zipfile.ZipFile(first) as archive:
        originals = {entry.filename: archive.read(entry) for entry in archive.infolist()}
    _normalize(first)
    _normalize(second)

    assert first.read_bytes() == second.read_bytes()
    for result in (first, second):
        with zipfile.ZipFile(result) as archive:
            assert {
                entry.filename: archive.read(entry) for entry in archive.infolist()
            } == originals
            assert {entry.date_time for entry in archive.infolist()} == {_FIXED}
        unchanged = result.read_bytes()
        _normalize(result)
        assert result.read_bytes() == unchanged


def test_mcpb_normalizer_fails_closed_on_corrupt_archive(tmp_path: Path) -> None:
    path = tmp_path / "invalid.mcpb"
    path.write_bytes(b"not a zip")
    with pytest.raises((ValueError, zipfile.BadZipFile)):
        _normalize(path)
    assert path.read_bytes() == b"not a zip"


def test_release_workflows_normalize_before_attestation_and_hashing() -> None:
    root = SCRIPT.parents[1]
    for name in ("prepare-mcpb.yml", "publish-mcpb.yml"):
        workflow = (root / ".github" / "workflows" / name).read_text(encoding="utf-8")
        normalizer = 'python3 scripts/normalize_mcpb_timestamps.py < "$output" > "$normalized"'
        assert workflow.count(normalizer) == 1
        assert workflow.index("npx -y @anthropic-ai/mcpb@2.1.2 pack") < workflow.index(normalizer)
        assert workflow.index(normalizer) < workflow.index('test -s "$output"')
        assert workflow.index(normalizer) < workflow.index('sha256sum "$artifact"')
