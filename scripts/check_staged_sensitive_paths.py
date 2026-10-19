"""Reject accidentally staged private configuration and key material by filename.

This lightweight check never reads or prints secret contents and does not need
network access. It is a first line of defense, not a replacement for Gitleaks.
"""

from __future__ import annotations

import sys
from pathlib import PurePosixPath

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


def main(staged_files: list[str] | None = None) -> int:
    """Validate staged paths supplied by Lefthook, without spawning any process."""
    paths = sys.argv[1:] if staged_files is None else staged_files
    blocked = [(path, reason) for path in paths if (reason := sensitive_reason(path)) is not None]
    if blocked:
        print("Sensitive filenames staged; unstage before committing:", file=sys.stderr)
        for path, reason in blocked:
            print(f"  {path}: {reason}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
