"""Configuration for KiCad MCP Pro."""

from __future__ import annotations

import threading
import warnings
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    TomlConfigSettingsSource,
)

from .discovery import discover_kicad_cli, discover_library_paths, scan_project_dir

CONFIG_FILE = Path.home() / ".config" / "kicad-mcp-pro" / "config.toml"


class KiCadMCPConfig(BaseSettings):
    """All server configuration in one place."""

    model_config = SettingsConfigDict(
        env_prefix="KICAD_MCP_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    kicad_cli: Path = Field(
        default_factory=discover_kicad_cli,
        description="Path to the kicad-cli executable.",
    )
    freerouting_jar: Path | None = Field(default=None)
    freerouting_image: str = Field(default="ghcr.io/freerouting/freerouting:latest")
    docker_executable: str = Field(default="docker")
    java_executable: str = Field(default="java")
    ngspice_cli: Path | None = Field(default=None)
    kicad_socket_path: Path | None = Field(default=None)
    kicad_token: str | None = Field(default=None)

    project_dir: Path | None = Field(default=None)
    project_file: Path | None = Field(default=None)
    pcb_file: Path | None = Field(default=None)
    sch_file: Path | None = Field(default=None)
    output_dir: Path | None = Field(default=None)

    symbol_library_dir: Path | None = Field(default=None)
    footprint_library_dir: Path | None = Field(default=None)

    transport: Literal["stdio", "http", "sse", "streamable-http"] = Field(default="stdio")
    host: str = Field(default="127.0.0.1")
    port: int = Field(default=3334)
    mount_path: str = Field(default="/mcp")
    profile: Literal["full", "minimal", "pcb", "schematic", "manufacturing"] = Field(default="full")
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = Field(default="INFO")
    log_format: Literal["json", "console"] = Field(default="console")

    enable_experimental_tools: bool = Field(default=False)
    ipc_connection_timeout: float = Field(default=10.0, gt=0.1, le=120.0)
    cli_timeout: float = Field(default=120.0, gt=0.1, le=600.0)
    max_items_per_response: int = Field(default=200, ge=1, le=2000)
    max_text_response_chars: int = Field(default=50000, ge=1000, le=500000)

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            TomlConfigSettingsSource(settings_cls, toml_file=CONFIG_FILE),
            file_secret_settings,
        )

    @field_validator(
        "kicad_cli",
        "freerouting_jar",
        "ngspice_cli",
        "kicad_socket_path",
        "project_dir",
        "project_file",
        "pcb_file",
        "sch_file",
        "output_dir",
        "symbol_library_dir",
        "footprint_library_dir",
        mode="before",
    )
    @classmethod
    def _normalize_paths(cls, value: object) -> object:
        if value in (None, ""):
            return None
        if isinstance(value, Path):
            return value.expanduser()
        if isinstance(value, str):
            return Path(value).expanduser()
        return value

    @field_validator("mount_path")
    @classmethod
    def _normalize_mount_path(cls, value: str) -> str:
        return value if value.startswith("/") else f"/{value}"

    @field_validator("kicad_cli")
    @classmethod
    def _validate_kicad_cli(cls, value: Path) -> Path:
        if not value.exists():
            warnings.warn(
                (
                    f"kicad-cli was not found at {value}. Export tools will remain unavailable "
                    "until KICAD_MCP_KICAD_CLI points to a valid executable."
                ),
                stacklevel=2,
            )
        return value

    @model_validator(mode="after")
    def resolve_paths(self) -> KiCadMCPConfig:
        """Resolve project-relative defaults."""
        self._refresh_paths()
        return self

    def _refresh_paths(self) -> None:
        """Refresh derived project and library paths."""
        if self.project_dir is None:
            for candidate in (self.project_file, self.pcb_file, self.sch_file):
                if candidate is not None:
                    self.project_dir = candidate.parent
                    break

        if self.project_dir is not None:
            scan = scan_project_dir(self.project_dir)
            self.project_file = self.project_file or scan["project"]
            self.pcb_file = self.pcb_file or scan["pcb"]
            self.sch_file = self.sch_file or scan["schematic"]
            self.output_dir = self.output_dir or self.project_dir / "output"

        libraries = discover_library_paths(self.kicad_cli)
        self.symbol_library_dir = self.symbol_library_dir or libraries.get("symbols")
        self.footprint_library_dir = self.footprint_library_dir or libraries.get("footprints")

    @property
    def project_root(self) -> Path:
        """Return the root directory used for path-safe operations."""
        if self.project_dir is not None:
            return self.project_dir.resolve()
        return Path.cwd().resolve()

    def ensure_output_dir(self, subdir: str | None = None) -> Path:
        """Create and return the output directory."""
        base = (self.output_dir or (self.project_root / "output")).resolve()
        target = base / subdir if subdir else base
        target.mkdir(parents=True, exist_ok=True)
        return target

    def resolve_within_project(self, raw_path: str | Path, *, allow_absolute: bool = False) -> Path:
        """Resolve a path relative to the project root and prevent traversal."""
        candidate = Path(raw_path).expanduser()
        if candidate.is_absolute():
            resolved = candidate.resolve()
            if not allow_absolute:
                self._assert_within_project(resolved)
            return resolved
        resolved = (self.project_root / candidate).resolve()
        self._assert_within_project(resolved)
        return resolved

    def _assert_within_project(self, path: Path) -> None:
        try:
            path.relative_to(self.project_root)
        except ValueError as exc:
            raise ValueError("The requested path escapes the active project directory.") from exc

    def apply_project(
        self,
        project_dir: Path,
        *,
        project_file: Path | None = None,
        pcb_file: Path | None = None,
        sch_file: Path | None = None,
        output_dir: Path | None = None,
    ) -> None:
        """Mutate the active project settings."""
        self.project_dir = project_dir.resolve()
        self.project_file = project_file.resolve() if project_file else None
        self.pcb_file = pcb_file.resolve() if pcb_file else None
        self.sch_file = sch_file.resolve() if sch_file else None
        self.output_dir = output_dir.resolve() if output_dir else self.project_dir / "output"
        self._refresh_paths()


_config_lock = threading.Lock()
_config: KiCadMCPConfig | None = None


def get_config() -> KiCadMCPConfig:
    """Return the lazy singleton config."""
    global _config
    with _config_lock:
        if _config is None:
            _config = KiCadMCPConfig()
    return _config


def reset_config() -> None:
    """Reset cached config for tests."""
    global _config
    with _config_lock:
        _config = None
