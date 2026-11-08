"""CLI lifecycle contract tests that never mutate installed tools."""

from __future__ import annotations

import json

from typer.testing import CliRunner

from kicad_mcp.cli_lifecycle import _install_manager, _manager_command
from kicad_mcp.cloud_user_cli import _local_pairing_storage_supported
from kicad_mcp.server import app


def test_windows_owner_key_storage_is_not_misreported_as_supported(monkeypatch) -> None:
    from types import SimpleNamespace

    from kicad_mcp import cloud_user_cli

    monkeypatch.setattr(cloud_user_cli, "os", SimpleNamespace(name="nt"))
    assert _local_pairing_storage_supported() is False


def test_package_manager_detection_only_accepts_known_tool_paths() -> None:
    assert (
        _install_manager("C:/Users/A/AppData/Roaming/uv/tools/kicad-mcp-pro/Scripts/python.exe")
        == "uv"
    )
    assert _install_manager("/home/a/.local/share/pipx/venvs/kicad-mcp-pro/bin/python") == "pipx"
    assert _install_manager("/usr/bin/python3") == "unknown"
    assert _manager_command("unknown", "uninstall") is None


def test_custom_uv_tool_dir_is_recognized_only_for_its_managed_interpreter(
    monkeypatch, tmp_path
) -> None:

    from kicad_mcp.cli_lifecycle import _install_manager

    tool_root = tmp_path / "custom-tools"
    managed = tool_root / "kicad-mcp-pro" / "Scripts" / "python.exe"
    another = tool_root / "unrelated-tool" / "Scripts" / "python.exe"
    monkeypatch.setenv("UV_TOOL_DIR", str(tool_root))
    assert _install_manager(managed) == "uv"
    assert _install_manager(another) == "unknown"
    assert _install_manager(tmp_path / "kicad-mcp-pro" / "Scripts" / "python.exe") == "unknown"
    assert _install_manager(tool_root / "kicad-mcp-pro" / "data" / "python.exe") == "unknown"
    monkeypatch.delenv("UV_TOOL_DIR")
    assert _install_manager(managed) == "unknown"


def test_custom_uv_tool_dir_respects_posix_python_symlinks(monkeypatch, tmp_path) -> None:
    import os
    import sys

    import pytest

    if os.name == "nt":
        pytest.skip("POSIX uv tools use external interpreter symlinks")

    from kicad_mcp.cli_lifecycle import _install_manager

    tool_root = tmp_path / "uv-tools"
    venv_bin = tool_root / "kicad-mcp-pro" / "bin"
    venv_bin.mkdir(parents=True)
    interpreter = venv_bin / "python"
    interpreter.symlink_to(sys.executable)
    monkeypatch.setenv("UV_TOOL_DIR", str(tool_root))
    assert interpreter.resolve() != interpreter.absolute()
    assert _install_manager(interpreter) == "uv"
    assert _install_manager(tmp_path / "other" / "bin" / "python") == "unknown"


def test_explicit_update_check_json_never_installs(monkeypatch) -> None:
    monkeypatch.setattr("kicad_mcp.cli_lifecycle._fetch_latest_stable", lambda: "99.0.0")
    monkeypatch.setattr("kicad_mcp.cli_lifecycle._install_manager", lambda: "uv")
    result = CliRunner().invoke(app, ["update", "check", "--json"])
    assert result.exit_code == 0, result.output
    report = json.loads(result.output)
    assert report["status"] == "update_available"
    assert report["upgrade_command"] == "uv tool upgrade kicad-mcp-pro"


def test_update_lookup_error_is_not_misreported_as_current(monkeypatch) -> None:
    from kicad_mcp.cli_lifecycle import ReleaseLookupError

    def offline() -> str:
        raise ReleaseLookupError("offline")

    monkeypatch.setattr("kicad_mcp.cli_lifecycle._fetch_latest_stable", offline)
    result = CliRunner().invoke(app, ["update", "check", "--json"])
    assert result.exit_code == 3
    assert json.loads(result.output)["status"] == "lookup_failed"


def test_offline_update_returns_stable_json_error_without_installing(monkeypatch) -> None:
    """Real HTTP path, no network: both update spellings must fail closed."""
    import urllib3.util.connection as transport

    calls: list[tuple[object, ...]] = []

    def offline(*args: object, **_kwargs: object) -> None:
        calls.append(args)
        raise OSError("simulated offline")

    monkeypatch.setattr(transport, "create_connection", offline)
    for args in (["update", "--json"], ["update", "check", "--json"]):
        result = CliRunner().invoke(app, args)
        assert result.exit_code == 3
        assert json.loads(result.output)["status"] == "lookup_failed"
        assert "update_available" not in result.output
    assert len(calls) == 2


def test_lifecycle_status_commands_never_check_network(monkeypatch) -> None:
    """MCP version and removal guidance remain offline and non-mutating."""
    import pytest

    def fail_network() -> str:
        pytest.fail("explicit update was not requested")

    monkeypatch.setattr("kicad_mcp.cli_lifecycle._fetch_latest_stable", fail_network)
    result = CliRunner().invoke(app, ["--version"])
    assert result.exit_code == 0, result.output
    result = CliRunner().invoke(app, ["uninstall"])
    assert result.exit_code == 0, result.output
    assert "No package, project or configuration was removed." in result.output


def test_uninstall_prints_command_without_touching_installed_files(monkeypatch) -> None:
    monkeypatch.setattr("kicad_mcp.cli_lifecycle._install_manager", lambda: "uv")
    result = CliRunner().invoke(app, ["uninstall"])
    assert result.exit_code == 0, result.output
    assert "uv tool uninstall kicad-mcp-pro" in result.output
    assert "No package, project or configuration was removed." in result.output


def test_unmanaged_pip_install_receives_conditional_removal_guidance(monkeypatch) -> None:
    monkeypatch.setattr("kicad_mcp.cli_lifecycle._install_manager", lambda: "unknown")
    result = CliRunner().invoke(app, ["uninstall"])
    assert result.exit_code == 0, result.output
    assert "If installed with pip" in result.output
    assert "-m pip uninstall kicad-mcp-pro" in result.output
    assert "uv tool uninstall" in result.output
    assert "pipx uninstall" in result.output
    assert "No package, project or configuration was removed." in result.output


def test_unmanaged_pip_update_is_guidance_only(monkeypatch) -> None:
    monkeypatch.setattr("kicad_mcp.cli_lifecycle._install_manager", lambda: "unknown")
    monkeypatch.setattr("kicad_mcp.cli_lifecycle._fetch_latest_stable", lambda: "99.0.0")
    result = CliRunner().invoke(app, ["update"])
    assert result.exit_code == 0, result.output
    assert "If installed with pip" in result.output
    assert "-m pip install --upgrade kicad-mcp-pro" in result.output
    assert "No update was installed automatically." in result.output


def test_checked_pypi_release_uses_tls_verified_exact_package_without_mutating(
    monkeypatch,
) -> None:
    from kicad_mcp.cli_lifecycle import _fetch_latest_stable

    recorded: list[str] = []

    class Response:
        status = 200

        def read(self, limit: int) -> bytes:
            assert limit > 1024
            recorded.append("read")
            return b'{"info":{"name":"kicad_mcp_pro","version":"99.0.0"}}'

        def release_conn(self) -> None:
            recorded.append("release")

    class Pool:
        def request(self, verb: str, path: str, **kwargs: object) -> Response:
            assert (verb, path) == ("GET", "/pypi/kicad-mcp-pro/json")
            assert kwargs["redirect"] is False
            recorded.append("request")
            return Response()

        def close(self) -> None:
            recorded.append("close")

    def factory(host: str, port: int, **kwargs: object) -> Pool:
        assert (host, port, kwargs["cert_reqs"]) == ("pypi.org", 443, "CERT_REQUIRED")
        return Pool()

    monkeypatch.setattr("kicad_mcp.cli_lifecycle.urllib3.HTTPSConnectionPool", factory)
    assert _fetch_latest_stable() == "99.0.0"
    assert recorded == ["request", "read", "release", "close"]


def test_checked_pypi_release_rejects_invalid_metadata_without_retry(
    monkeypatch,
) -> None:
    import pytest

    from kicad_mcp.cli_lifecycle import ReleaseLookupError, _fetch_latest_stable

    cases = [
        (503, b'{"info":{"name":"kicad-mcp-pro","version":"99.0.0"}}'),
        (200, b'{"info":{"name":"other-package","version":"99.0.0"}}'),
        (200, b'{"info":{"name":"kicad-mcp-pro","version":"99.0.0rc1"}}'),
        (200, b'{"info":{"name":"kicad-mcp-pro","version":"not-a-version"}}'),
        (200, b"not-json"),
    ]

    def check_case(status: int, blob: bytes) -> None:
        seen: list[str] = []

        class Response:
            def __init__(self) -> None:
                self.status = status

            def read(self, _limit: int) -> bytes:
                seen.append("read")
                return blob

            def release_conn(self) -> None:
                seen.append("release")

        class Pool:
            def request(self, *_a: object, **_kw: object) -> Response:
                seen.append("request")
                return Response()

            def close(self) -> None:
                seen.append("close")

        monkeypatch.setattr(
            "kicad_mcp.cli_lifecycle.urllib3.HTTPSConnectionPool",
            lambda *_a, **_kw: Pool(),
        )
        with pytest.raises(ReleaseLookupError):
            _fetch_latest_stable()
        assert seen[-2:] == ["release", "close"]
        assert seen.count("request") == 1

    for status, blob in cases:
        check_case(status, blob)


def test_pypi_release_metadata_size_limit_is_fail_closed(monkeypatch) -> None:
    import pytest

    from kicad_mcp.cli_lifecycle import (
        ReleaseLookupError,
        _fetch_latest_stable,
    )

    class Response:
        status = 200

        def read(self, limit: int) -> bytes:
            return b"x" * limit

        def release_conn(self) -> None:
            return

    class Pool:
        def request(self, *_a: object, **_kw: object) -> Response:
            return Response()

        def close(self) -> None:
            return

    monkeypatch.setattr(
        "kicad_mcp.cli_lifecycle.urllib3.HTTPSConnectionPool",
        lambda *_a, **_kw: Pool(),
    )
    with pytest.raises(ReleaseLookupError, match="size limit"):
        _fetch_latest_stable()


def test_plain_update_covers_current_and_known_manager_commands(monkeypatch) -> None:
    from kicad_mcp.cli_lifecycle import _manager_command

    assert _manager_command("pipx", "upgrade") == "pipx upgrade kicad-mcp-pro"
    assert _manager_command("pipx", "uninstall") == "pipx uninstall kicad-mcp-pro"

    monkeypatch.setattr("kicad_mcp.cli_lifecycle._fetch_latest_stable", lambda: "1.0.0")
    current = CliRunner().invoke(app, ["update"])
    assert current.exit_code == 0
    assert "Already up to date" in current.output

    monkeypatch.setattr("kicad_mcp.cli_lifecycle._fetch_latest_stable", lambda: "99.0.0")
    monkeypatch.setattr("kicad_mcp.cli_lifecycle._install_manager", lambda: "pipx")
    later = CliRunner().invoke(app, ["update"])
    assert later.exit_code == 0
    assert "Upgrade using your package manager: pipx upgrade kicad-mcp-pro" in later.output

    def fail() -> str:
        from kicad_mcp.cli_lifecycle import ReleaseLookupError

        raise ReleaseLookupError("index offline")

    monkeypatch.setattr("kicad_mcp.cli_lifecycle._fetch_latest_stable", fail)
    offline = CliRunner().invoke(app, ["update"])
    assert offline.exit_code == 3
    assert "Update check unavailable: index offline" in offline.output
    assert "installed version has not been changed" in offline.output


def test_setup_without_agent_is_safe_in_noninteractive_mode(monkeypatch) -> None:
    monkeypatch.setattr(
        "kicad_mcp.setup.run_wizard", lambda: (_ for _ in ()).throw(AssertionError("wizard"))
    )
    result = CliRunner().invoke(app, ["setup"])
    assert result.exit_code == 2
    assert "interactive terminal" in result.output


def test_setup_agent_option_is_an_alias_for_existing_positional(monkeypatch) -> None:
    monkeypatch.setattr(
        "kicad_mcp.setup.setup_agent",
        lambda agent, **_kw: f"configuration preview for {agent}",
    )
    result = CliRunner().invoke(app, ["setup", "--agent", "claude-code"])
    assert result.exit_code == 0, result.output
    assert "configuration preview for claude-code" in result.output


def test_setup_rejects_ambiguous_agent_selection() -> None:
    result = CliRunner().invoke(app, ["setup", "codex", "--agent", "claude-code"])
    assert result.exit_code != 0


def test_path_inventory_detects_multiple_launchers_without_executing_them(tmp_path) -> None:
    from kicad_mcp.cli_lifecycle import _path_launchers

    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    (first / "kicad-mcp-pro.exe").touch()
    (second / "kicad-mcp-pro.exe").touch()
    found = _path_launchers([str(first), str(second), str(first)], windows=True)
    assert len(found) == 2
    assert found[0].replace(chr(92), "/").endswith("first/kicad-mcp-pro.exe")


def test_doctor_warns_about_duplicate_launchers_without_running_them(monkeypatch) -> None:
    from kicad_mcp.diagnostics import _duplicate_cli_path_check

    monkeypatch.setattr(
        "kicad_mcp.cli_lifecycle._path_launchers",
        lambda: ["first/kicad-mcp-pro.exe", "second/kicad-mcp-pro.exe"],
    )
    check = _duplicate_cli_path_check()
    assert check is not None
    assert check.name == "cli_path_conflict"
    assert check.status == "warn"
    assert "first/kicad-mcp-pro.exe" in check.message
    assert "second/kicad-mcp-pro.exe" in check.hint
    assert "Get-Command" in check.hint


def test_direct_windows_enrollment_cannot_create_unprotected_key_or_send_request(
    monkeypatch, tmp_path
) -> None:
    from types import SimpleNamespace

    import pytest

    from kicad_mcp import cloud_pair

    keyfile = tmp_path / "device.pem"
    monkeypatch.setattr(cloud_pair, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(
        cloud_pair,
        "_post",
        lambda *_args, **_kwargs: pytest.fail("no Cloud HTTP allowed"),
    )
    with pytest.raises(cloud_pair.CloudPairingError, match="Windows"):
        cloud_pair.start_enrollment("https://cloud.example", "Demo", keyfile)
    assert not keyfile.exists()
    assert not list(tmp_path.iterdir())


def test_connector_service_failure_does_not_fabricate_enabled_state(monkeypatch, tmp_path) -> None:
    from kicad_mcp.cloud_user_cli import _start_connector

    monkeypatch.setattr(
        "kicad_mcp.cloud_managed_connector._enable",
        lambda: (_ for _ in ()).throw(RuntimeError("systemd unavailable")),
    )
    monkeypatch.setattr(
        "kicad_mcp.cloud_pair_keys._write_private_json",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("must not create enabled marker as fallback")
        ),
    )
    assert _start_connector(tmp_path, {}) == "Unavailable"
    assert not list(tmp_path.iterdir())


def test_windows_connector_enable_rejects_before_creating_enabled_marker(
    monkeypatch, tmp_path
) -> None:
    from types import SimpleNamespace

    import pytest

    from kicad_mcp import cloud_managed_connector

    monkeypatch.setattr(cloud_managed_connector, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(cloud_managed_connector, "default_registry_root", lambda: tmp_path)
    monkeypatch.setattr(
        cloud_managed_connector,
        "_single_registered_identity",
        lambda *_args: pytest.fail("unsupported service must not access registration"),
    )
    with pytest.raises(RuntimeError, match="unsupported"):
        cloud_managed_connector._enable()
    assert not list(tmp_path.iterdir())
    assert cloud_managed_connector._status() == "Off"
