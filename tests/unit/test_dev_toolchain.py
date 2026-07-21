from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

from scripts.dev_environment import load_toolchain_contract

ROOT = Path(__file__).resolve().parents[2]


def test_toolchain_contract_is_exact_and_cross_file_consistent() -> None:
    contract = load_toolchain_contract(ROOT)

    assert contract.python_version == "3.13.12"
    assert contract.uv_version == "0.10.8"
    assert contract.node_version == "24.11.0"
    assert contract.pnpm_version == "11.5.0"
    assert contract.task_version == "3.52.0"
    assert contract.rustup_version == "1.29.0"
    assert contract.rust_toolchain == "1.97.1"
    assert contract.kicad_cli_version == "10.0.4"
    assert contract.supported_architectures == ("aarch64", "x86_64")

    package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    uv_config = tomllib.loads((ROOT / "uv.toml").read_text(encoding="utf-8"))
    rust_config = tomllib.loads((ROOT / "rust-toolchain.toml").read_text(encoding="utf-8"))

    assert (ROOT / ".python-version").read_text(encoding="utf-8").strip() == contract.python_version
    assert package["packageManager"] == f"pnpm@{contract.pnpm_version}"
    assert package["engines"]["node"].startswith(f">={contract.node_version} ")
    assert uv_config["required-version"] == contract.uv_version
    assert rust_config["toolchain"]["channel"] == contract.rust_toolchain


def test_toolchain_contract_has_pinned_linux_download_checksums() -> None:
    contract = load_toolchain_contract(ROOT)
    sha256 = re.compile(r"^[0-9a-f]{64}$")

    for architecture in contract.supported_architectures:
        downloads = contract.downloads[architecture]
        assert set(downloads) == {"node", "rustup", "task", "uv"}
        for download in downloads.values():
            assert download.url.startswith("https://")
            assert sha256.fullmatch(download.sha256)
            assert download.archive_name in download.url


def test_local_development_roots_are_ignored() -> None:
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    for path in (".dev-cache/", ".dev-env.sh", ".dev-tools/"):
        assert path in gitignore
