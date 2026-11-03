"""No real login, device enrollment, key or service change in CLI command tests."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from kicad_mcp.server import app


def test_login_opens_only_first_party_browser_and_saves_no_local_token(monkeypatch) -> None:
    seen: list[str] = []
    monkeypatch.setattr(
        "kicad_mcp.cloud_user_cli.webbrowser.open", lambda url, **_kwargs: seen.append(url) or True
    )
    result = CliRunner().invoke(app, ["cloud", "login"])
    assert result.exit_code == 0, result.output
    assert seen == ["https://kicad-mcp-pro.oaslananka.dev/sign-in"]
    assert "Browser login does not grant device or project access." in result.output
    assert "cloud connect" in result.output


def test_login_headless_prints_link_but_never_launches_browser(monkeypatch) -> None:
    monkeypatch.setattr(
        "kicad_mcp.cloud_user_cli.webbrowser.open",
        lambda *_args, **_kw: pytest.fail("no browser expected"),
    )
    result = CliRunner().invoke(app, ["cloud", "login", "--no-browser"])
    assert result.exit_code == 0, result.output
    assert "https://kicad-mcp-pro.oaslananka.dev/sign-in" in result.output


@pytest.mark.parametrize(
    "origin",
    [
        "http://kicad-mcp-pro.oaslananka.dev",
        "https://user:password@site.example",
        "https://site.example/path",
        "https://site.example?token=secret",
        "https://site.example/#fragment",
        "javascript:alert(1)",
    ],
)
def test_cloud_login_rejects_unsafe_origins_without_opening_browser(
    monkeypatch, origin: str
) -> None:
    monkeypatch.setattr(
        "kicad_mcp.cloud_user_cli.webbrowser.open",
        lambda *_args, **_kw: pytest.fail("invalid origin"),
    )
    result = CliRunner().invoke(app, ["cloud", "login", "--cloud-origin", origin])
    assert result.exit_code != 0


def test_cloud_connect_reuses_existing_signed_pairing_flow(monkeypatch, tmp_path) -> None:
    called: list[list[str]] = []
    monkeypatch.setattr(
        "kicad_mcp.cloud_local_registry.default_registry_root", lambda: tmp_path / "unregistered"
    )
    monkeypatch.setattr("kicad_mcp.cloud_pair.main", lambda args: called.append(args) or 0)
    result = CliRunner().invoke(app, ["cloud", "connect", "--alias", "Lab board"])
    assert result.exit_code == 0, result.output
    assert called == [
        [
            "--cloud-origin",
            "https://kicad-mcp-pro.oaslananka.dev",
            "--alias",
            "Lab board",
            "--begin-pairing",
        ]
    ]
    assert "does not enable the persistent Connector" in result.output


@pytest.mark.parametrize("command", ["status", "enable", "disable"])
def test_cloud_connector_commands_delegate_to_existing_owner_managed_boundary(
    monkeypatch, command: str
) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(
        "kicad_mcp.cloud_managed_connector.main", lambda args: calls.append(args) or 0
    )
    result = CliRunner().invoke(app, ["cloud", command])
    assert result.exit_code == 0, result.output
    assert calls == [[command]]


def test_cloud_connect_does_not_pair_an_already_registered_project(monkeypatch, tmp_path) -> None:
    registry = tmp_path / "cloud"
    (registry / "projects").mkdir(parents=True)
    (registry / "projects" / "fixture.json").write_text("fixture", encoding="utf-8")
    monkeypatch.setattr("kicad_mcp.cloud_local_registry.default_registry_root", lambda: registry)
    monkeypatch.setattr(
        "kicad_mcp.cloud_registered_pilot._single_registered_identity",
        lambda _root: {"cloudOrigin": "https://kicad-mcp-pro.oaslananka.dev"},
    )
    monkeypatch.setattr(
        "kicad_mcp.cloud_pair.main",
        lambda *_args: pytest.fail("must not re-enroll an existing project"),
    )
    result = CliRunner().invoke(app, ["cloud", "connect"])
    assert result.exit_code == 0, result.output
    assert "Cloud enrollment has NOT been verified" in result.output
    assert "cloud connect --new-device" in result.output
    assert "existing local registration and keys were not changed" in result.output


def test_cloud_connect_rejects_ambiguous_registration_before_enrollment(
    monkeypatch, tmp_path
) -> None:
    registry = tmp_path / "cloud"
    (registry / "projects").mkdir(parents=True)
    (registry / "projects" / "fixture.json").write_text("fixture", encoding="utf-8")
    monkeypatch.setattr("kicad_mcp.cloud_local_registry.default_registry_root", lambda: registry)

    def invalid(_root):
        raise ValueError("ambiguous project")

    monkeypatch.setattr("kicad_mcp.cloud_registered_pilot._single_registered_identity", invalid)
    monkeypatch.setattr(
        "kicad_mcp.cloud_pair.main",
        lambda *_args: pytest.fail("ambiguous registration cannot trigger new key"),
    )
    result = CliRunner().invoke(app, ["cloud", "connect"])
    assert result.exit_code != 0
    assert "Existing Cloud registration needs local repair" in result.output


def test_cloud_connect_explicit_new_device_preserves_existing_local_registration(
    monkeypatch, tmp_path
) -> None:
    registry = tmp_path / "cloud"
    projects = registry / "projects"
    projects.mkdir(parents=True)
    existing = projects / "fixture.json"
    existing.write_text("private-existing-record", encoding="utf-8")
    monkeypatch.setattr("kicad_mcp.cloud_local_registry.default_registry_root", lambda: registry)
    monkeypatch.setattr(
        "kicad_mcp.cloud_registered_pilot._single_registered_identity",
        lambda _root: {"cloudOrigin": "https://kicad-mcp-pro.oaslananka.dev"},
    )
    called: list[list[str]] = []
    monkeypatch.setattr("kicad_mcp.cloud_pair.main", lambda args: called.append(args) or 0)
    result = CliRunner().invoke(app, ["cloud", "connect", "--new-device"])
    assert result.exit_code == 0, result.output
    assert len(called) == 1
    assert called[0][-1] == "--begin-pairing"
    assert existing.read_text(encoding="utf-8") == "private-existing-record"
    assert "Existing registration and keys will be preserved" in result.output
    assert "local project registry must also reference that new" in result.output


def test_cloud_connect_new_device_rejects_corrupt_existing_registration(
    monkeypatch, tmp_path
) -> None:
    registry = tmp_path / "cloud"
    (registry / "projects").mkdir(parents=True)
    (registry / "projects" / "fixture.json").write_text("untrusted", encoding="utf-8")
    monkeypatch.setattr("kicad_mcp.cloud_local_registry.default_registry_root", lambda: registry)
    monkeypatch.setattr(
        "kicad_mcp.cloud_registered_pilot._single_registered_identity",
        lambda _root: (_ for _ in ()).throw(ValueError("corrupt")),
    )
    monkeypatch.setattr(
        "kicad_mcp.cloud_pair.main",
        lambda _args: pytest.fail("corrupt existing registration must fail closed"),
    )
    result = CliRunner().invoke(app, ["cloud", "connect", "--new-device"])
    assert result.exit_code != 0
    assert "Existing Cloud registration needs local repair" in result.output
