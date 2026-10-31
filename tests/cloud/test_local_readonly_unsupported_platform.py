"""Fail-closed tests when safe directory descriptor semantics are unavailable."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from kicad_mcp.cloud_readonly_boundary import (
    LocalReadDeniedError,
    OperatorProject,
    VerifiedLocalBinding,
    inspect_readonly,
)

DEVICE = "11111111-1111-4111-8111-111111111111"
PROJECT = "22222222-2222-4222-8222-222222222222"
NOW = 1_800_000_000_000
SESSION = "44444444-4444-4444-8444-444444444444"


def test_missing_nofollow_flag_rejected_even_for_valid_request(tmp_path: Path) -> None:
    folder = tmp_path / "operator"
    folder.mkdir()
    (folder / "sample.kicad_pro").write_text("synthetic", encoding="utf-8")
    frame = json.dumps(
        {
            "kind": "connector.read_request",
            "version": 1,
            "requestId": "33333333-3333-4333-8333-333333333333",
            "deviceId": DEVICE,
            "projectId": PROJECT,
            "operation": "project_summary",
            "deadlineUnixMs": NOW + 1000,
        },
        separators=(",", ":"),
    ).encode("utf-8")
    with patch.object(os, "O_NOFOLLOW", None, create=True):
        _raise_argument_1 = VerifiedLocalBinding(
            DEVICE, PROJECT, frozenset({"project_summary"}), SESSION, NOW + 60000
        )
        _raise_argument_2 = OperatorProject(DEVICE, PROJECT, folder, "sample")
        with pytest.raises(LocalReadDeniedError):
            inspect_readonly(
                frame,
                verified=_raise_argument_1,
                operator_project=_raise_argument_2,
                now_unix_ms=NOW,
            )
