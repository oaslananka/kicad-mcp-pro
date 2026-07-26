"""Execute the repository-pinned uv binary from the bootstrap contract."""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from shutil import which

ROOT = Path(__file__).resolve().parents[1]


def required_uv_version(root: Path = ROOT) -> str:
    """Read the reviewed uv version from ``scripts/dev-toolchain.env``."""
    contract = root / "scripts" / "dev-toolchain.env"
    for raw_line in contract.read_text(encoding="utf-8").splitlines():
        key, separator, value = raw_line.partition("=")
        if separator and key.strip() == "UV_VERSION":
            version = value.strip()
            if version:
                return version
    raise RuntimeError(f"UV_VERSION is missing from {contract}")


def _read_uv_version(binary: Path) -> str:
    completed = subprocess.run(
        [str(binary), "--version"],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        return ""
    parts = completed.stdout.strip().split()
    return parts[1] if len(parts) >= 2 and parts[0] == "uv" else ""


def resolve_uv(
    *,
    root: Path = ROOT,
    environ: Mapping[str, str] | None = None,
    path_lookup: Callable[[str], str | None] = which,
    version_reader: Callable[[Path], str] = _read_uv_version,
) -> Path:
    """Resolve a uv binary that exactly matches the repository contract."""
    values = os.environ if environ is None else environ
    expected = required_uv_version(root)
    override = values.get("KICAD_MCP_UV", "").strip()
    managed_root = root / ".dev-tools" / "uv" / expected / "bin"

    candidates: list[Path] = []
    if override:
        candidates.append(Path(override).expanduser())
    candidates.extend((managed_root / "uv", managed_root / "uv.exe"))
    global_uv = path_lookup("uv")
    if global_uv:
        candidates.append(Path(global_uv))

    seen: set[Path] = set()
    mismatches: list[str] = []
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved in seen or not resolved.is_file():
            continue
        seen.add(resolved)
        actual = version_reader(resolved)
        if actual == expected:
            return resolved
        mismatches.append(f"{resolved}={actual or 'unreadable'}")

    details = ", ".join(mismatches) if mismatches else "no uv binary found"
    raise RuntimeError(
        f"Required uv {expected} is unavailable ({details}). "
        "Run `task dev:bootstrap` (or `./scripts/bootstrap-dev.sh --core-only`) "
        "and retry. Advanced environments may set KICAD_MCP_UV to an exact matching binary."
    )


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if not arguments:
        print("Usage: python scripts/run_uv.py <uv arguments...>", file=sys.stderr)
        return 2
    try:
        binary = resolve_uv()
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    environment = dict(os.environ)
    environment["KICAD_MCP_UV"] = str(binary)
    completed = subprocess.run(
        [str(binary), *arguments],
        check=False,
        env=environment,
    )
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
