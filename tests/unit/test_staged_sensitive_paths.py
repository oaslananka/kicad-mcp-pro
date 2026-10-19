"""Fast, file-content-free pre-commit sensitive path blocking."""

from __future__ import annotations

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


def test_only_sensitive_paths_are_reported(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert (
        check_staged_sensitive_paths.main(
            ["docs/okay.md", "certificates/my key.pem", "src/package.py"]
        )
        == 1
    )
    output = capsys.readouterr().err
    assert "certificates/my key.pem" in output
    assert "docs/okay.md" not in output
    assert "src/package.py" not in output


def test_safe_staged_paths_pass_without_git_or_network() -> None:
    assert check_staged_sensitive_paths.main(["docs/okay.md", ".env.example"]) == 0
