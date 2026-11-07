"""Experience state transitions require real scope and never invent Cloud readiness."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from kicad_mcp.services.experience import (
    ReadinessStatus,
    calculate_experience_snapshot,
    current_experience_snapshot,
    sanitize_experience_for_cloud,
)


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({}, ReadinessStatus.ACCOUNT_REQUIRED),
        (
            {"account_authenticated": True, "device_paired": True, "has_kicad_project": False},
            ReadinessStatus.PROJECT_SELECTION_REQUIRED,
        ),
        (
            {"account_authenticated": True, "device_paired": True, "client_granted": True},
            ReadinessStatus.CONNECTOR_DISABLED,
        ),
        (
            {
                "account_authenticated": True,
                "device_paired": True,
                "client_granted": True,
                "cloud_connector_enabled": True,
                "cloud_connector_status": "connecting",
            },
            ReadinessStatus.CONNECTOR_CONNECTING,
        ),
        (
            {
                "account_authenticated": True,
                "device_paired": True,
                "client_granted": True,
                "cloud_connector_enabled": True,
                "cloud_connector_status": "unreachable",
            },
            ReadinessStatus.CONNECTOR_UNREACHABLE,
        ),
        (
            {
                "account_authenticated": True,
                "device_paired": True,
                "client_granted": True,
                "cloud_connector_enabled": True,
                "cloud_connector_status": "connected",
            },
            ReadinessStatus.READY,
        ),
    ],
)
def test_cloud_steps_are_independent(
    tmp_path: Path, overrides: dict[str, object], expected: ReadinessStatus
) -> None:
    data: dict[str, object] = {
        "mode": "cloud",
        "project_dir": tmp_path,
        "has_kicad_project": True,
        "cli_available": True,
        "account_authenticated": False,
    }
    data.update(overrides)
    result = calculate_experience_snapshot(**data)
    assert result.readiness == expected
    assert result.reason_code != "local_ready"


def test_cloud_view_strips_nested_credentials_and_local_paths(tmp_path: Path) -> None:
    result = calculate_experience_snapshot(
        mode="cloud",
        project_dir=tmp_path,
        has_kicad_project=True,
        account_authenticated=True,
        device_paired=True,
        ai_client_name="client",
        client_granted=True,
        cloud_connector_enabled=True,
        cloud_connector_status="connected",
        computer_id="local-machine",
    )
    # Derive synthetic test input at runtime rather than committing a
    # password-shaped literal; the redaction assertion still checks its value.
    synthetic_password = f"fixture-only-{tmp_path.name}"
    result.account = {"bearer_token": "private-value", "password": synthetic_password}
    result.ai_client = {
        "name": "client",
        "secret": "private-value",
        "nested": [{"path": "C:/work/board", "status": "pending"}],
    }
    safe = sanitize_experience_for_cloud(result)
    assert str(tmp_path) not in str(safe)
    assert "private-value" not in str(safe)
    assert synthetic_password not in str(safe)
    assert "C:/work/board" not in str(safe)
    assert safe["readiness"] == ReadinessStatus.READY
    assert safe["project"]["valid"] is True


def test_local_engine_missing_on_invalidated_project_location(tmp_path: Path) -> None:
    removed = tmp_path / "previous-project"
    result = calculate_experience_snapshot(
        mode="local",
        project_dir=removed,
        has_kicad_project=True,
        cli_available=False,
        ipc_available=False,
    )
    assert result.readiness == ReadinessStatus.ENGINE_CAPABILITY_UNAVAILABLE
    assert result.next_action is not None
    assert result.next_action.id == "install_kicad"


def test_runtime_snapshot_uses_current_local_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import kicad_mcp.config as config
    import kicad_mcp.discovery as discovery

    (tmp_path / "board.kicad_pro").write_text("{}", encoding="utf-8")
    cli = tmp_path / "kicad-cli"
    cli.write_text("mock executable", encoding="utf-8")
    monkeypatch.setattr(
        config,
        "get_config",
        lambda: SimpleNamespace(project_dir=tmp_path, kicad_cli=cli),
    )
    monkeypatch.setattr(discovery, "find_kicad_version", lambda *_: "10.0.8")
    result = current_experience_snapshot()
    assert result.readiness == ReadinessStatus.READY
    assert result.engine_capabilities.cli_available
    assert result.project["name"] == tmp_path.name
