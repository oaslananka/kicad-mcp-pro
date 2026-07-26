from __future__ import annotations

from pathlib import Path

import pytest
from pytest import MonkeyPatch

from scripts.run_uv import required_uv_version, resolve_uv


def test_required_uv_version_reads_toolchain_contract(tmp_path: Path) -> None:
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "dev-toolchain.env").write_text(
        "PYTHON_VERSION=3.13.12\nUV_VERSION=0.10.8\n",
        encoding="utf-8",
    )

    assert required_uv_version(tmp_path) == "0.10.8"


def test_resolve_uv_prefers_repository_bootstrap(tmp_path: Path) -> None:
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "dev-toolchain.env").write_text("UV_VERSION=0.10.8\n", encoding="utf-8")
    managed = tmp_path / ".dev-tools" / "uv" / "0.10.8" / "bin" / "uv"
    managed.parent.mkdir(parents=True)
    managed.write_text("managed", encoding="utf-8")

    resolved = resolve_uv(
        root=tmp_path,
        environ={},
        path_lookup=lambda _name: "/usr/bin/uv",
        version_reader=lambda path: "0.10.8" if path == managed else "0.11.32",
    )

    assert resolved == managed


def test_resolve_uv_accepts_explicit_override(tmp_path: Path) -> None:
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "dev-toolchain.env").write_text("UV_VERSION=0.10.8\n", encoding="utf-8")
    override = tmp_path / "tools" / "uv"
    override.parent.mkdir()
    override.write_text("override", encoding="utf-8")

    resolved = resolve_uv(
        root=tmp_path,
        environ={"KICAD_MCP_UV": str(override)},
        path_lookup=lambda _name: None,
        version_reader=lambda _path: "0.10.8",
    )

    assert resolved == override


def test_resolve_uv_rejects_only_mismatched_global_uv(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "dev-toolchain.env").write_text("UV_VERSION=0.10.8\n", encoding="utf-8")
    global_uv = tmp_path / "global-uv"
    global_uv.write_text("global", encoding="utf-8")
    monkeypatch.setenv("PATH", str(tmp_path))

    with pytest.raises(RuntimeError, match="task dev:bootstrap"):
        resolve_uv(
            root=tmp_path,
            environ={},
            path_lookup=lambda _name: str(global_uv),
            version_reader=lambda _path: "0.11.32",
        )
