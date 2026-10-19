"""Reject accidentally staged private configuration and key material by filename.

This lightweight check never reads or prints secret contents and does not need
network access. It is a first line of defense, not a replacement for Gitleaks.
"""

from __future__ import annotations

import subprocess  # nosec B404 -- controlled, fixed-argument Git invocation.
import sys
from pathlib import PurePosixPath
from shutil import which

_PRIVATE_NAMES = frozenset(
    {".npmrc", ".pypirc", "id_rsa", "id_ed25519", "credentials.json", "service-account.json"}
)
_PRIVATE_SUFFIXES = (".pem", ".key", ".p12", ".pfx")
_ALLOWED_ENV_SUFFIXES = (".example", ".sample", ".template")


def sensitive_reason(path: str) -> str | None:
    """Return a category, without reading the potentially sensitive file."""
    name = PurePosixPath(path).name.lower()
    if name == ".env" or name.startswith(".env."):
        if not name.endswith(_ALLOWED_ENV_SUFFIXES):
            return "private environment configuration"
    if (
        name in _PRIVATE_NAMES
        or (name.startswith("id_rsa.") and name != "id_rsa.pub")
        or (name.startswith("id_ed25519.") and name != "id_ed25519.pub")
    ):
        return "private credential/key filename"
    if name.endswith(_PRIVATE_SUFFIXES):
        return "private key/certificate filename"
    return None


def main() -> int:
    git_binary = which("git")
    if git_binary is None:
        print("sensitive paths: required Git executable not found", file=sys.stderr)
        return 2
    completed = subprocess.run(  # nosec B603 -- fixed argv, no shell.
        ["git", "diff", "--cached", "--name-only", "-z", "--diff-filter=ACMR"],  # noqa: S607 -- fixed Git subcommand, no shell.
        capture_output=True,
        check=False,
    )
    if completed.returncode:
        print("sensitive paths: unable to read Git index", file=sys.stderr)
        return completed.returncode
    blocked: list[tuple[str, str]] = []
    for raw in completed.stdout.split(b"\0"):
        if not raw:
            continue
        path = raw.decode("utf-8", errors="surrogateescape")
        reason = sensitive_reason(path)
        if reason:
            blocked.append((path, reason))
    if blocked:
        print("Sensitive filenames staged; unstage before committing:", file=sys.stderr)
        for path, reason in blocked:
            print(f"  {path}: {reason}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
