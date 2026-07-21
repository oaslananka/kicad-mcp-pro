"""Repository-scoped development toolchain contract and diagnostics helpers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

_VERSION = re.compile(r"^\d+\.\d+\.\d+$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ARCHITECTURES = ("aarch64", "x86_64")
_DOWNLOAD_TOOLS = ("node", "rustup", "task", "uv")


@dataclass(frozen=True)
class DownloadSpec:
    """One checksum-pinned native tool download."""

    url: str
    sha256: str

    @property
    def archive_name(self) -> str:
        return Path(urlparse(self.url).path).name


@dataclass(frozen=True)
class DevToolchainContract:
    """Exact repository development toolchain contract."""

    python_version: str
    uv_version: str
    node_version: str
    pnpm_version: str
    task_version: str
    rustup_version: str
    rust_toolchain: str
    kicad_cli_version: str
    supported_architectures: tuple[str, ...]
    downloads: dict[str, dict[str, DownloadSpec]]


def _parse_contract_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"Invalid toolchain contract line {line_number}: {raw_line!r}")
        key, value = line.split("=", 1)
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*", key) or not value:
            raise ValueError(f"Invalid toolchain contract line {line_number}: {raw_line!r}")
        if key in values:
            raise ValueError(f"Duplicate toolchain contract key: {key}")
        values[key] = value
    return values


def _required(values: dict[str, str], key: str) -> str:
    try:
        return values[key]
    except KeyError as exc:
        raise ValueError(f"Missing toolchain contract key: {key}") from exc


def load_toolchain_contract(root: Path) -> DevToolchainContract:
    """Load and validate the exact repository development toolchain contract."""

    values = _parse_contract_file(root / "scripts" / "dev-toolchain.env")
    if _required(values, "KICAD_MCP_DEV_TOOLCHAIN_SCHEMA") != "1":
        raise ValueError("Unsupported development toolchain schema")

    versions = {
        "python_version": _required(values, "PYTHON_VERSION"),
        "uv_version": _required(values, "UV_VERSION"),
        "node_version": _required(values, "NODE_VERSION"),
        "pnpm_version": _required(values, "PNPM_VERSION"),
        "task_version": _required(values, "TASK_VERSION"),
        "rustup_version": _required(values, "RUSTUP_VERSION"),
        "rust_toolchain": _required(values, "RUST_TOOLCHAIN"),
        "kicad_cli_version": _required(values, "KICAD_CLI_VERSION"),
    }
    for name, version in versions.items():
        if not _VERSION.fullmatch(version):
            raise ValueError(f"Invalid exact version for {name}: {version}")

    architectures = tuple(sorted(_required(values, "SUPPORTED_ARCHITECTURES").split(",")))
    if architectures != _ARCHITECTURES:
        raise ValueError(f"Unsupported architecture contract: {architectures}")

    downloads: dict[str, dict[str, DownloadSpec]] = {}
    for architecture in architectures:
        architecture_downloads: dict[str, DownloadSpec] = {}
        suffix = architecture.upper()
        for tool in _DOWNLOAD_TOOLS:
            prefix = f"{tool.upper()}_{suffix}"
            url = _required(values, f"{prefix}_URL")
            sha256 = _required(values, f"{prefix}_SHA256")
            parsed = urlparse(url)
            if parsed.scheme != "https" or not parsed.netloc:
                raise ValueError(f"Invalid HTTPS URL for {tool}/{architecture}: {url}")
            if not _SHA256.fullmatch(sha256):
                raise ValueError(f"Invalid SHA-256 for {tool}/{architecture}: {sha256}")
            architecture_downloads[tool] = DownloadSpec(url=url, sha256=sha256)
        downloads[architecture] = architecture_downloads

    return DevToolchainContract(
        supported_architectures=architectures,
        downloads=downloads,
        **versions,
    )
