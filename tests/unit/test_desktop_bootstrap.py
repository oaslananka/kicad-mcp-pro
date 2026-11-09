"""Release bootstrap staging only copies the pinned setup-uv executable."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from scripts.prepare_desktop_bootstrap import stage

ROOT = Path(__file__).resolve().parents[2]


def test_stage_uses_exact_source_bytes_without_executing_a_binary(tmp_path: Path) -> None:
    source = tmp_path / "uv.exe"
    source.write_bytes(b"synthetic test-owned executable bytes")
    output = tmp_path / "resource"
    filename, digest = stage(source, output)
    assert filename in ("uv", "uv.exe")
    assert (output / filename).read_bytes() == source.read_bytes()
    assert digest == hashlib.sha256(source.read_bytes()).hexdigest()
    assert source.read_bytes() == b"synthetic test-owned executable bytes"


def test_stage_replaces_only_own_binary_and_removes_platform_stale_entry(tmp_path: Path) -> None:
    source = tmp_path / "source-uv"
    source.write_bytes(b"new")
    output = tmp_path / "bundle"
    output.mkdir()
    (output / "uv").write_bytes(b"old")
    (output / "uv.exe").write_bytes(b"old")
    filename, digest = stage(source, output)
    assert (output / filename).read_bytes() == b"new"
    assert digest == hashlib.sha256(b"new").hexdigest()
    stale = output / ("uv" if filename == "uv.exe" else "uv.exe")
    assert not stale.exists()


def test_refuses_missing_binary_without_creating_output(tmp_path: Path) -> None:
    output = tmp_path / "resources"
    with pytest.raises(RuntimeError, match="unavailable"):
        stage(tmp_path / "missing", output)
    assert not output.exists()


def test_release_workflow_checks_version_before_staging() -> None:
    workflow = (ROOT / ".github/workflows/gui-release.yml").read_text(encoding="utf-8")
    gate = workflow.index("Verify exact pinned desktop bootstrap version")
    stage_step = workflow.index("Stage pinned app-owned uv")
    build_step = workflow.index("Build Tauri installer")
    assert gate < stage_step < build_step
    assert "uv --version" in workflow
    assert "uv.toml" in workflow
    assert "Installed uv version does not match uv.toml" in workflow


def test_desktop_cold_start_timeout_and_managed_python_are_consistent() -> None:
    """A real 160-second cold Windows uv setup must not time out at 120 sec."""
    import re

    rust = (ROOT / "src-tauri/src/lib.rs").read_text(encoding="utf-8")
    splash = (ROOT / "src-tauri/frontend/index.html").read_text(encoding="utf-8")
    native = re.search(r"const HEALTH_WAIT: Duration = Duration::from_secs\((\d+)\)", rust)
    frontend = re.search(r"const MAX_RETRIES = (\d+);", splash)
    assert native is not None
    assert frontend is not None
    assert int(native.group(1)) >= 180
    assert int(frontend.group(1)) > int(native.group(1))
    assert '.env("UV_PYTHON", "3.13")' in rust
    assert '.env("UV_PYTHON_PREFERENCE", "only-managed")' in rust


def test_desktop_diagnostic_command_matches_actual_native_command() -> None:
    rust = (ROOT / "src-tauri/src/lib.rs").read_text(encoding="utf-8")
    splash = (ROOT / "src-tauri/frontend/index.html").read_text(encoding="utf-8")
    assert '"uv tool run --from {} kicad-mcp-pro dashboard' in rust
    assert "command.startsWith('uv tool run --from kicad-mcp-pro==')" in splash


def test_splash_native_actions_are_not_inline_handlers() -> None:
    """CSP-safe DOM listeners must wire native error and recovery actions."""
    splash = (ROOT / "src-tauri/frontend/index.html").read_text(encoding="utf-8")
    assert "onclick=" not in splash
    for element_id in (
        "cancelStartup",
        "btnCopyCmd",
        "useSeparatePort",
        "btnCancel",
        "restartBackend",
        "retryBackend",
    ):
        assert f'id="{element_id}"' in splash
        assert f"['{element_id}', " in splash
    assert "document.getElementById(id).addEventListener('click', handler)" in splash
