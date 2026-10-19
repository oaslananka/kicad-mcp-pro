"""Fast, file-content-free pre-commit sensitive path blocking."""

from __future__ import annotations

from unittest.mock import Mock

import pytest

from scripts import check_staged_sensitive_paths


@pytest.mark.parametrize(
    "path",
    [
        ".env",
        ".env.local",
        "subdir/.env.production",
        ".npmrc",
        "settings/.pypirc",
        "keys/id_ed25519",
        "keys/id_rsa.bak",
        "config/credentials.json",
        "dev/service-account.json",
        "certificates/server.pem",
        "keys/server.key",
        "certificates/signing.p12",
        "certificates/client.pfx",
    ],
)
def test_sensitive_filename_blocked(path: str) -> None:
    assert check_staged_sensitive_paths.sensitive_reason(path) is not None


@pytest.mark.parametrize(
    "path",
    [
        ".env.example",
        ".env.production.example",
        "config/.env.sample",
        "docs/.env.template",
        "README.md",
        "config.json",
        "docs/credentials.example.json",
        "keys/id_rsa.pub",
        "keys/id_ed25519.pub",
        "src/kicad_mcp/server.py",
    ],
)
def test_example_and_source_paths_allowed(path: str) -> None:
    assert check_staged_sensitive_paths.sensitive_reason(path) is None


def test_index_check_is_binary_safe_and_avoids_printing_contents(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    runner = Mock(return_value=Mock(returncode=0, stdout=b"docs/okay.md\0keys/a.pem\0"))
    monkeypatch.setattr(check_staged_sensitive_paths.subprocess, "run", runner)
    monkeypatch.setattr(check_staged_sensitive_paths, "which", lambda _: "/usr/bin/git")
    assert check_staged_sensitive_paths.main() == 1
    output = capsys.readouterr().err
    assert "keys/a.pem" in output
    assert "docs/okay.md" not in output
    runner.assert_called_once()
    assert runner.call_args.args[0] == [
        "git",
        "diff",
        "--cached",
        "--name-only",
        "-z",
        "--diff-filter=ACMR",
    ]
