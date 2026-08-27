from __future__ import annotations

import os
from pathlib import Path

import pytest

from kicad_mcp.config import KiCadMCPConfig, get_config
from kicad_mcp.discovery import poll_studio_watch_dir


def test_config_reads_env_vars(sample_project: Path, monkeypatch) -> None:
    monkeypatch.setenv("KICAD_MCP_LOG_LEVEL", "DEBUG")
    cfg = KiCadMCPConfig()
    assert cfg.project_dir == sample_project
    assert cfg.log_level == "DEBUG"


def test_logging_config_accepts_text_warn_critical_and_rotating_file(
    sample_project: Path,
    tmp_path: Path,
) -> None:
    _ = sample_project
    warning_cfg = KiCadMCPConfig(
        log_level="warn",
        log_format="text",
        log_file=tmp_path / "server.log",
    )
    critical_cfg = KiCadMCPConfig(log_level="critical")

    assert warning_cfg.log_level == "WARNING"
    assert warning_cfg.log_format == "text"
    assert warning_cfg.log_file == tmp_path / "server.log"
    assert critical_cfg.log_level == "CRITICAL"


def test_config_auto_detects_files(sample_project: Path) -> None:
    cfg = KiCadMCPConfig()
    assert cfg.project_file == sample_project / "demo.kicad_pro"
    assert cfg.pcb_file == sample_project / "demo.kicad_pcb"
    assert cfg.sch_file == sample_project / "demo.kicad_sch"


def test_config_resolve_within_project(sample_project: Path) -> None:
    cfg = KiCadMCPConfig()
    resolved = cfg.resolve_within_project("exports/demo.txt")
    assert resolved == sample_project / "exports" / "demo.txt"


def test_config_derives_project_dir_from_explicit_files(tmp_path: Path, fake_cli: Path) -> None:
    project = tmp_path / "derived"
    project.mkdir()
    schematic = project / "derived.kicad_sch"
    schematic.write_text("(kicad_sch)\n", encoding="utf-8")

    cfg = KiCadMCPConfig(kicad_cli=fake_cli, sch_file=schematic)

    assert cfg.project_dir == project
    assert cfg.sch_file == schematic
    assert cfg.output_dir == project / "output"


def test_mount_path_is_normalized_without_trailing_slash(sample_project: Path) -> None:
    _ = sample_project
    cfg = KiCadMCPConfig(mount_path="api/")
    assert cfg.mount_path == "/api"


def test_cors_origins_require_explicit_http_urls(sample_project: Path) -> None:
    _ = sample_project
    cfg = KiCadMCPConfig(cors_origins="https://example.com,http://localhost:3334")
    assert cfg.cors_origin_list == ["https://example.com", "http://localhost:3334"]

    with pytest.raises(ValueError, match="cannot contain '\\*'"):
        KiCadMCPConfig(cors_origins="*")

    vscode_cfg = KiCadMCPConfig(cors_origins="vscode-webview://panel")
    assert vscode_cfg.cors_origin_list == ["vscode-webview://panel"]

    with pytest.raises(ValueError, match="must be fully qualified"):
        KiCadMCPConfig(cors_origins="file://panel")


EXPOSED_IPV4 = ".".join(("0", "0", "0", "0"))
EXPOSED_IPV6 = "::"
LAN_IPV4 = ".".join(("192", "168", "1", "10"))


@pytest.mark.parametrize("host", [EXPOSED_IPV4, EXPOSED_IPV6, LAN_IPV4])
def test_http_transport_requires_auth_on_exposed_hosts(
    sample_project: Path,
    host: str,
) -> None:
    _ = sample_project

    with pytest.raises(ValueError, match="requires auth_token"):
        KiCadMCPConfig(transport="streamable-http", host=host)


def test_http_transport_requires_strong_token_on_exposed_hosts(sample_project: Path) -> None:
    _ = sample_project

    with pytest.raises(ValueError, match="at least 32 characters"):
        KiCadMCPConfig(transport="streamable-http", host=EXPOSED_IPV4, auth_token="x" * 8)


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "::1"])
def test_http_transport_allows_loopback_without_token(sample_project: Path, host: str) -> None:
    _ = sample_project

    cfg = KiCadMCPConfig(transport="http", host=host)

    assert cfg.transport == "streamable-http"
    assert cfg.host == host
    assert cfg.auth_token is None


def test_http_transport_rejects_plaintext_exposed_host_even_with_strong_token(
    sample_project: Path,
) -> None:
    _ = sample_project
    credential = "x" * 32

    with pytest.raises(ValueError, match="TLS or a protected public endpoint"):
        KiCadMCPConfig(
            transport="streamable-http",
            host=EXPOSED_IPV4,
            auth_token=credential,
        )


def test_http_transport_allows_exposed_bind_behind_loopback_boundary(
    sample_project: Path,
) -> None:
    _ = sample_project
    credential = "x" * 32

    cfg = KiCadMCPConfig(
        transport="streamable-http",
        host=EXPOSED_IPV4,
        auth_token=credential,
        http_boundary="loopback-proxy",
        public_base_url="http://127.0.0.1:3334",
    )

    assert cfg.auth_token == credential
    assert cfg.public_base_url == "http://127.0.0.1:3334"


def test_http_transport_allows_exposed_bind_behind_https_boundary(
    sample_project: Path,
) -> None:
    _ = sample_project

    cfg = KiCadMCPConfig(
        transport="streamable-http",
        host=EXPOSED_IPV4,
        auth_token="x" * 32,
        http_boundary="tls-proxy",
        public_base_url="https://mcp.example.test/",
    )

    assert cfg.public_base_url == "https://mcp.example.test"


def test_http_transport_rejects_public_url_without_explicit_proxy_boundary(
    sample_project: Path,
) -> None:
    _ = sample_project

    with pytest.raises(ValueError, match="explicit http_boundary"):
        KiCadMCPConfig(
            transport="streamable-http",
            host=EXPOSED_IPV4,
            auth_token="x" * 32,
            public_base_url="http://127.0.0.1:3334",
        )


def test_loopback_proxy_boundary_requires_bind_all_host(sample_project: Path) -> None:
    _ = sample_project

    with pytest.raises(ValueError, match="loopback-proxy requires a bind-all host"):
        KiCadMCPConfig(
            transport="streamable-http",
            host=LAN_IPV4,
            auth_token="x" * 32,
            http_boundary="loopback-proxy",
            public_base_url="http://127.0.0.1:3334",
        )


def test_http_transport_rejects_remote_plaintext_public_base_url(sample_project: Path) -> None:
    _ = sample_project

    with pytest.raises(ValueError, match="public_base_url must use HTTPS or loopback HTTP"):
        KiCadMCPConfig(
            transport="streamable-http",
            host=EXPOSED_IPV4,
            auth_token="x" * 32,
            public_base_url="http://192.168.1.42:3334",
        )


def test_http_transport_accepts_direct_tls_certificate_pair(
    sample_project: Path, tmp_path: Path
) -> None:
    _ = sample_project
    cert = tmp_path / "server.crt"
    key = tmp_path / "server.key"
    cert.write_text("certificate", encoding="utf-8")
    key.write_text("private-key", encoding="utf-8")

    cfg = KiCadMCPConfig(
        transport="streamable-http",
        host=LAN_IPV4,
        auth_token="x" * 32,
        tls_cert_file=cert,
        tls_key_file=key,
    )

    assert cfg.tls_cert_file == cert
    assert cfg.tls_key_file == key
    assert cfg.advertised_http_base_url == f"https://{LAN_IPV4}:3334"


def test_direct_tls_rejects_plaintext_public_base_url(sample_project: Path, tmp_path: Path) -> None:
    _ = sample_project
    cert = tmp_path / "server.crt"
    key = tmp_path / "server.key"
    cert.write_text("certificate", encoding="utf-8")
    key.write_text("private-key", encoding="utf-8")

    with pytest.raises(ValueError, match="direct TLS public_base_url must use HTTPS"):
        KiCadMCPConfig(
            transport="streamable-http",
            host=LAN_IPV4,
            auth_token="x" * 32,
            tls_cert_file=cert,
            tls_key_file=key,
            public_base_url="http://127.0.0.1:3334",
        )


def test_http_transport_rejects_incomplete_tls_certificate_pair(
    sample_project: Path, tmp_path: Path
) -> None:
    _ = sample_project
    cert = tmp_path / "server.crt"
    cert.write_text("certificate", encoding="utf-8")

    with pytest.raises(
        ValueError, match="tls_cert_file and tls_key_file must be configured together"
    ):
        KiCadMCPConfig(
            transport="streamable-http",
            host=LAN_IPV4,
            auth_token="x" * 32,
            tls_cert_file=cert,
        )


def test_watch_dir_does_not_override_explicit_project(tmp_path: Path, monkeypatch) -> None:
    explicit_project = tmp_path / "explicit"
    explicit_project.mkdir()
    (explicit_project / "explicit.kicad_pro").write_text("{}", encoding="utf-8")
    (explicit_project / "explicit.kicad_pcb").write_text("(kicad_pcb)\n", encoding="utf-8")
    (explicit_project / "explicit.kicad_sch").write_text("(kicad_sch)\n", encoding="utf-8")

    watch_project = tmp_path / "watch" / "demo"
    watch_project.mkdir(parents=True)
    (watch_project / "demo.kicad_pro").write_text("{}", encoding="utf-8")
    (watch_project / "demo.kicad_pcb").write_text("(kicad_pcb)\n", encoding="utf-8")
    (watch_project / "demo.kicad_sch").write_text("(kicad_sch)\n", encoding="utf-8")

    monkeypatch.setenv("KICAD_MCP_PROJECT_DIR", str(explicit_project))
    cfg = get_config()

    poll_studio_watch_dir(tmp_path / "watch", previous={})

    assert cfg.project_dir == explicit_project.resolve()


def test_watch_dir_auto_selection_does_not_create_explicit_lock(tmp_path: Path) -> None:
    watch_root = tmp_path / "watch"
    first_project = watch_root / "first"
    second_project = watch_root / "second"
    for project in (first_project, second_project):
        project.mkdir(parents=True)
        (project / f"{project.name}.kicad_pro").write_text("{}", encoding="utf-8")
        (project / f"{project.name}.kicad_pcb").write_text("(kicad_pcb)\n", encoding="utf-8")
        (project / f"{project.name}.kicad_sch").write_text("(kicad_sch)\n", encoding="utf-8")

    os.utime(first_project / "first.kicad_pro", (1_000_000, 1_000_000))
    os.utime(second_project / "second.kicad_pro", (999_000, 999_000))

    cfg = get_config()
    previous = poll_studio_watch_dir(watch_root, previous={})
    assert cfg.project_dir == first_project.resolve()
    assert cfg.project_dir_is_explicit is False

    os.utime(second_project / "second.kicad_pro", (1_001_000, 1_001_000))
    poll_studio_watch_dir(watch_root, previous=previous)
    assert cfg.project_dir == second_project.resolve()
    assert cfg.project_dir_is_explicit is False


def test_config_filter_runtime_tools(monkeypatch) -> None:
    monkeypatch.setenv("KICAD_MCP_FILTER_RUNTIME_TOOLS", "false")
    cfg = KiCadMCPConfig()
    assert cfg.filter_runtime_tools is False
