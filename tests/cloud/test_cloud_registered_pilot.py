"""Offline security boundaries for the reboot-independent registered owner CLI."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

from kicad_mcp import cloud_operator_pilot, cloud_registered_pilot

pytestmark = pytest.mark.skipif(os.name != "posix", reason="POSIX owner registry required")
DEVICE = "11111111-1111-4111-8111-111111111111"
PROJECT = "22222222-2222-4222-8222-222222222222"


def _registered(tmp_path: Path) -> Path:
    root = tmp_path / "registered"
    (root / "projects").mkdir(parents=True, mode=0o700)
    (root / "keys").mkdir(mode=0o700)
    (root / "keys" / f"{DEVICE}.pem").write_text("synthetic")
    (root / "keys" / f"{DEVICE}.pem").chmod(0o600)
    target = tmp_path / "project"
    target.mkdir()
    record = root / "projects" / f"{PROJECT}.json"
    record.write_text(
        json.dumps(
            {
                "ownerSub": "owner-fixture",
                "cloudOrigin": "https://cloud.example",
                "deviceId": DEVICE,
                "projectId": PROJECT,
                "keySlot": DEVICE,
                "directory": str(target),
                "filenameStem": "example",
            }
        )
    )
    record.chmod(0o600)
    return root


def test_registered_pilot_denies_headless_before_reading_registration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(
        cloud_registered_pilot,
        "default_registry_root",
        lambda: pytest.fail("headless access must not read any owner registry"),
    )
    assert cloud_registered_pilot.main([]) == 1


@pytest.mark.parametrize(
    "mode", ["presence", "inspection", "native-drc", "board-counts", "schematic-counts"]
)
def test_registered_pilot_uses_existing_owner_approval(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, mode: str
) -> None:
    root = _registered(tmp_path)
    monkeypatch.setattr(cloud_registered_pilot, "default_registry_root", lambda: root)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    invoked: list[list[str]] = []

    def fake_pilot(argv: list[str]) -> int:
        invoked.append(argv)
        return 0

    monkeypatch.setattr(cloud_operator_pilot, "main", fake_pilot)
    assert cloud_registered_pilot.main(["--mode", mode]) == 0
    args = invoked[0]
    assert args[:2] == ["--cloud-origin", "https://cloud.example"]
    assert args[args.index("--device-id") + 1] == DEVICE
    assert args[args.index("--project-id") + 1] == PROJECT
    assert "--allow-once" in args
    if mode == "presence":
        assert not any(flag in args for flag in ("--native-drc-once", "--inspection-once"))
    else:
        assert cloud_registered_pilot._MODE_FLAGS[mode][0] in args


@pytest.mark.parametrize(
    "tamper", ["none", "two", "wrong_name", "symlink", "loose", "duplicate_id", "key_missing"]
)
def test_registered_pilot_denies_ambiguous_or_unsafe_registry(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, tamper: str
) -> None:
    root = _registered(tmp_path)
    record = root / "projects" / f"{PROJECT}.json"
    if tamper == "none":
        record.unlink()
    elif tamper == "two":
        (root / "projects" / f"{DEVICE}.json").write_text("{}")
    elif tamper == "wrong_name":
        record.rename(root / "projects" / "unsafe.json")
    elif tamper == "symlink":
        original = tmp_path / "original.json"
        record.rename(original)
        record.symlink_to(original)
    elif tamper == "loose":
        record.chmod(0o644)
    elif tamper == "duplicate_id":
        record.write_text(
            record.read_text().replace('"deviceId":', '"deviceId":"other","deviceId":', 1)
        )
    else:
        (root / "keys" / f"{DEVICE}.pem").unlink()
    monkeypatch.setattr(cloud_registered_pilot, "default_registry_root", lambda: root)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr(
        cloud_operator_pilot,
        "main",
        lambda _: pytest.fail("unsafe registration must not reach signing"),
    )
    assert cloud_registered_pilot.main([]) == 1
