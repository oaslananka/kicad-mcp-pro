"""Published GUI bootstrap staging: exact uv version and app-owned artifact."""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.prepare_desktop_bootstrap import stage


def test_stages_matching_version_without_global_install(tmp_path: Path) -> None:
    source = tmp_path / "uv.exe"
    source.write_bytes(b"synthetic test-owned executable bytes")
    out = tmp_path / "resource"
    with patch(
        "scripts.prepare_desktop_bootstrap.subprocess.run",
        return_value=subprocess.CompletedProcess(
            [str(source), "--version"], 0, stdout=b"uv 0.13.5 (test-build x86_64-pc-windows-msvc)"
        ),
    ) as run:
        filename, digest = stage(source, out, "0.13.5")
    run.assert_called_once_with(
        [str(source), "--version"], capture_output=True, check=False, timeout=12
    )
    assert filename in ("uv", "uv.exe")
    assert (out / filename).read_bytes() == source.read_bytes()
    assert digest == hashlib.sha256(source.read_bytes()).hexdigest()
    assert source.is_file()


@pytest.mark.parametrize(
    "version,exit_code",
    [("uv 0.13.4", 0), ("uv 99.0", 0), ("uv 0.13.5", 1)],
)
def test_refuses_unpinned_or_failing_binary(tmp_path: Path, version: str, exit_code: int) -> None:
    source = tmp_path / "uv.exe"
    source.write_bytes(b"synthetic")
    out = tmp_path / "resources"
    with patch(
        "scripts.prepare_desktop_bootstrap.subprocess.run",
        return_value=subprocess.CompletedProcess(
            [str(source), "--version"], exit_code, stdout=version.encode()
        ),
    ):
        with pytest.raises(RuntimeError, match="pinned release runtime"):
            stage(source, out, "0.13.5")
    assert not out.exists()


def test_refuses_missing_binary_without_creating_output(tmp_path: Path) -> None:
    output = tmp_path / "resources"
    with pytest.raises(RuntimeError, match="unavailable"):
        stage(tmp_path / "missing", output, "0.13.5")
    assert not output.exists()
