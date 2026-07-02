"""Configuration for KiCad MCP Pro."""

from __future__ import annotations

import os
import threading
import warnings
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from pydantic import Field, PrivateAttr, field_validator, model_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    TomlConfigSettingsSource,
)

from .path_safety import assert_within, normalize_workspace_root, relative_subpath, resolve_under

CONFIG_FILE = Path.home() / ".config" / "kicad-mcp-pro" / "config.toml"
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def _discover_kicad_cli() -> Path:
    from .discovery import discover_kicad_cli

    return discover_kicad_cli()


def _discover_library_paths(cli_path: Path) -> dict[str, Path | None]:
    from .discovery import discover_library_paths

    return discover_library_paths(cli_path)


def _scan_project_dir(project_dir: Path) -> dict[str, Path | None]:
    from .discovery import scan_project_dir

    return scan_project_dir(project_dir)


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
        default_factory=_discover_kicad_cli,
        description="Path to the kicad-cli executable.",
    )
    freerouting_jar: Path | None = Field(default=None)
    freerouting_image: str = Field(default="ghcr.io/freerouting/freerouting:2.1.0")
    docker_executable: str = Field(default="docker")
    java_executable: str = Field(default="java")
    freerouting_timeout_sec: float = Field(default=900.0, gt=1.0, le=7200.0)
    ngspice_cli: Path | None = Field(default=None)
    kicad_socket_path: Path | None = Field(default=None)
    kicad_token: str | None = Field(default=None)
    workspace_root: Path | None = Field(default=None)

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
    cors_origins: str = Field(default="")
    auth_token: str | None = Field(default=None)
    allow_query_token_auth: bool = Field(default=False)
    legacy_sse: bool = Field(default=False)
    stateful_http: bool = Field(default=False)
    enable_metrics: bool = Field(default=False)
    telemetry_enabled: bool = Field(default=False)
    otel_endpoint: str | None = Field(default=None)
    otel_headers: str = Field(default="")
    otel_service_name: str = Field(default="kicad-mcp-pro")
    otel_protocol: Literal["http/protobuf", "grpc"] = Field(default="http/protobuf")
    telemetry_buffer_max_events: int = Field(default=100, ge=0, le=1000)
    studio_watch_dir: Path | None = Field(default=None)
    profile: Literal[
        "full",
        "expert",
        "minimal",
        "beginner",
        "read_only_inspection",
        "schematic_only",
        "schematic_authoring",
        "pcb_only",
        "pcb_layout",
        "manufacturing",
        "manufacturing_release",
        "builder",
        "critic",
        "release_manager",
        "high_speed",
        "power",
        "simulation",
        "analysis",
        "pcb",
        "schematic",
        "agent_full",
    ] = Field(default="full")
    operating_mode: Literal["readonly", "write", "manufacturing", "experimental"] = Field(
        default="readonly",
        description="Risk-oriented tool exposure mode.",
    )
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(default="INFO")
    log_format: Literal["json", "text", "console"] = Field(default="console")
    log_file: Path | None = Field(default=None)
    log_max_bytes: int = Field(default=5_000_000, ge=1024, le=1_000_000_000)
    log_backup_count: int = Field(default=3, ge=1, le=20)

    enable_experimental_tools: bool = Field(default=False)
    enable_tasks: bool = Field(
        default=False,
        description=(
            "Opt-in to the experimental MCP Tasks extension for draft/future MCP protocol work."
        ),
    )
    filter_runtime_tools: bool = Field(
        default=True,
        description="Filter out tools requiring live KiCad IPC if the connection is down.",
    )
    ipc_connection_timeout: float = Field(default=10.0, gt=0.1, le=120.0)
    ipc_retries: int = Field(default=2, ge=0, le=10)
    ipc_cache_ttl: float = Field(default=5.0, gt=0.5, le=60.0)
    headless: bool = Field(default=False)
    cli_timeout: float = Field(default=120.0, gt=0.1, le=600.0)
    max_items_per_response: int = Field(default=200, ge=1, le=2000)
    max_text_response_chars: int = Field(default=50000, ge=1000, le=500000)
    _project_dir_explicit: bool = PrivateAttr(default=False)

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        import sys

        # Skip loading local .env files during pytest runs to avoid test pollution
        if "pytest" in sys.modules:
            return (
                init_settings,
                env_settings,
                TomlConfigSettingsSource(settings_cls, toml_file=CONFIG_FILE),
                file_secret_settings,
            )
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            TomlConfigSettingsSource(settings_cls, toml_file=CONFIG_FILE),
            file_secret_settings,
        )

    @model_validator(mode="before")
    @classmethod
    def _apply_env_aliases(cls, values: object) -> object:
        """Apply interoperability aliases that do not fit the KICAD_MCP_ prefix."""
        if not isinstance(values, dict):
            return values

        aliases = {
            "kicad_token": ("KICAD_API_TOKEN", "KICAD_MCP_KICAD_TOKEN"),
            "kicad_socket_path": ("KICAD_API_SOCKET", "KICAD_MCP_KICAD_SOCKET_PATH"),
            "kicad_cli": ("KICAD_CLI_PATH", "KICAD_MCP_KICAD_CLI"),
            "workspace_root": ("KICAD_MCP_WORKSPACE_ROOT",),
            "ipc_retries": ("KICAD_MCP_RETRIES",),
            "headless": ("KICAD_MCP_HEADLESS",),
            "otel_endpoint": ("OTEL_EXPORTER_OTLP_ENDPOINT",),
            "otel_headers": ("OTEL_EXPORTER_OTLP_HEADERS",),
            "otel_service_name": ("OTEL_SERVICE_NAME",),
            "otel_protocol": ("OTEL_EXPORTER_OTLP_PROTOCOL",),
        }
        updated = dict(values)
        for field_name, env_names in aliases.items():
            if field_name in updated and updated[field_name] not in (None, ""):
                continue
            for env_name in env_names:
                raw = os.environ.get(env_name)
                if raw not in (None, ""):
                    updated[field_name] = raw
                    break

        if "ipc_connection_timeout" not in updated or updated["ipc_connection_timeout"] in (
            None,
            "",
        ):
            timeout_ms = os.environ.get("KICAD_MCP_TIMEOUT_MS")
            if timeout_ms not in (None, ""):
                updated["ipc_connection_timeout"] = float(str(timeout_ms)) / 1000.0

        if updated.get("otel_endpoint") not in (None, ""):
            updated["telemetry_enabled"] = True

        return updated

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
        "workspace_root",
        "symbol_library_dir",
        "footprint_library_dir",
        "log_file",
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
        normalized = value.strip() or "/"
        if not normalized.startswith("/"):
            normalized = f"/{normalized}"
        if len(normalized) > 1:
            normalized = normalized.rstrip("/")
        return normalized

    @field_validator("cors_origins")
    @classmethod
    def _validate_cors_origins(cls, value: str) -> str:
        origins = [item.strip() for item in value.split(",") if item.strip()]
        for origin in origins:
            if origin == "*":
                raise ValueError(
                    "KICAD_MCP_CORS_ORIGINS cannot contain '*'. "
                    "Use an explicit local origin allowlist instead."
                )
            parsed = urlparse(origin)
            if parsed.scheme not in {"http", "https", "vscode-webview"} or not parsed.netloc:
                raise ValueError(
                    "KICAD_MCP_CORS_ORIGINS entries must be fully qualified "
                    "http://, https://, or vscode-webview:// URLs."
                )
        return ",".join(origins)

    @field_validator("transport", mode="before")
    @classmethod
    def _normalize_transport(cls, value: object) -> object:
        if isinstance(value, str):
            normalized = value.strip().casefold()
            if normalized == "http":
                return "streamable-http"
            return normalized
        return value

    @field_validator("log_level", mode="before")
    @classmethod
    def _normalize_log_level(cls, value: object) -> object:
        if isinstance(value, str):
            normalized = value.strip().upper()
            return "WARNING" if normalized == "WARN" else normalized
        return value

    @field_validator("log_format", "profile", "otel_protocol", mode="before")
    @classmethod
    def _normalize_lowercase_literals(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip().casefold()
        return value

    @field_validator("operating_mode", mode="before")
    @classmethod
    def _normalize_operating_mode(cls, value: object) -> object:
        if value in (None, ""):
            return "readonly"
        if isinstance(value, str):
            normalized = value.strip().casefold().replace("_", "-")
            aliases = {"read-only": "readonly", "ro": "readonly", "mfg": "manufacturing"}
            return aliases.get(normalized, normalized)
        return value

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
        self._project_dir_explicit = self.project_dir is not None and (
            "project_dir" in self.model_fields_set
        )
        self._refresh_paths()
        self._validate_http_transport_security()
        return self

    def _validate_http_transport_security(self) -> None:
        """Fail closed before exposing HTTP transports on non-loopback interfaces."""
        if self.transport == "stdio":
            return
        exposed_host = self.host.strip().casefold() not in LOOPBACK_HOSTS
        if exposed_host and not self.auth_token:
            raise ValueError("HTTP transport on non-loopback host requires auth_token")
        if exposed_host and self.auth_token and len(self.auth_token) < 32:
            raise ValueError("HTTP auth_token for non-loopback host must be at least 32 characters")

    def _refresh_paths(self) -> None:
        """Refresh derived project and library paths."""
        if self.project_dir is None:
            for candidate in (self.project_file, self.pcb_file, self.sch_file):
                if candidate is not None:
                    self.project_dir = candidate.parent
                    break

        if self.project_dir is not None:
            scan = _scan_project_dir(self.project_dir)
            self.project_file = self.project_file or scan["project"]
            self.pcb_file = self.pcb_file or scan["pcb"]
            self.sch_file = self.sch_file or scan["schematic"]
            self.output_dir = self.output_dir or self.project_dir / "output"

        libraries = _discover_library_paths(self.kicad_cli)
        self.symbol_library_dir = self.symbol_library_dir or libraries.get("symbols")
        self.footprint_library_dir = self.footprint_library_dir or libraries.get("footprints")
        self._validate_workspace_membership()

    def _validate_workspace_membership(self) -> None:
        """Ensure configured project paths stay under an explicit workspace root."""
        if self.workspace_root is None:
            return
        root = self.workspace_root.resolve()
        for path in (
            self.project_dir,
            self.project_file,
            self.pcb_file,
            self.sch_file,
            self.output_dir,
        ):
            if path is not None:
                assert_within(root, path.resolve())

    @property
    def project_root(self) -> Path:
        """Return the root directory used for path-safe operations."""
        if self.project_dir is not None:
            return self.project_dir.resolve()
        return Path.cwd().resolve()

    @property
    def workspace(self) -> Path:
        """Return the root directory used for workspace-safe operations."""
        return normalize_workspace_root(self.workspace_root, fallback=self.project_root)

    @property
    def timeout_ms(self) -> int:
        """Return the IPC timeout in milliseconds for diagnostics."""
        return int(self.ipc_connection_timeout * 1000)

    def ensure_output_dir(self, subdir: str | None = None) -> Path:
        """Create and return the output directory."""
        base = (self.output_dir or (self.project_root / "output")).resolve()
        assert_within(self.workspace, base)
        target = base
        if subdir:
            candidate = relative_subpath(subdir)
            target = (base / candidate).resolve()
            try:
                target.relative_to(base)
            except ValueError as exc:
                raise ValueError("The requested output directory escapes the output root.") from exc
            assert_within(self.workspace, target)
        target.mkdir(parents=True, exist_ok=True)
        return target

    def resolve_within_project(self, raw_path: str | Path, *, allow_absolute: bool = False) -> Path:
        """Resolve a path relative to the project root and prevent traversal."""
        resolved = resolve_under(self.project_root, raw_path, allow_absolute=allow_absolute)
        self._assert_within_project(resolved)
        assert_within(self.workspace, resolved)
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
        explicit: bool = True,
    ) -> None:
        """Mutate the active project settings."""
        self.project_dir = project_dir.resolve()
        self.project_file = project_file.resolve() if project_file else None
        self.pcb_file = pcb_file.resolve() if pcb_file else None
        self.sch_file = sch_file.resolve() if sch_file else None
        self.output_dir = output_dir.resolve() if output_dir else self.project_dir / "output"
        self._validate_workspace_membership()
        self._project_dir_explicit = explicit
        self._refresh_paths()

    @property
    def cors_origin_list(self) -> list[str]:
        """Return configured CORS origins as a normalized list."""
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    @property
    def project_dir_is_explicit(self) -> bool:
        """Return True when the active project came from explicit user configuration."""
        return self._project_dir_explicit

    def safe_diagnostics(self) -> dict[str, object]:
        """Return sanitized config values for health and doctor output."""
        return {
            "workspace_root": str(self.workspace) if self.workspace else None,
            "project_dir": str(self.project_dir) if self.project_dir else None,
            "project_file": str(self.project_file) if self.project_file else None,
            "pcb_file": str(self.pcb_file) if self.pcb_file else None,
            "sch_file": str(self.sch_file) if self.sch_file else None,
            "output_dir": str(self.output_dir) if self.output_dir else None,
            "timeout_ms": self.timeout_ms,
            "retries": self.ipc_retries,
            "headless": self.headless,
            "log_level": self.log_level,
            "log_format": self.log_format,
            "telemetry_enabled": self.telemetry_enabled,
            "otel_endpoint": {"configured": self.otel_endpoint is not None},
            "otel_headers": {"configured": bool(self.otel_headers)},
            "otel_service_name": self.otel_service_name,
            "otel_protocol": self.otel_protocol,
            "telemetry_buffer_max_events": self.telemetry_buffer_max_events,
            "transport": self.transport,
            "host": self.host,
            "port": self.port,
            "mount_path": self.mount_path,
            "stateful_http": self.stateful_http,
            "auth_token": {"configured": self.auth_token is not None},
            "kicad_token": {"configured": self.kicad_token is not None},
        }


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
