"""Stage the pinned uv runtime into a Tauri release bundle.

Only release builds call this; no global installs, no downloads, and no
repository-owned binaries. The setup-uv Action provides the pinned executable.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "src-tauri" / "resources" / "bootstrap"


def stage(executable: Path, destination: Path, required_version: str) -> tuple[str, str]:
    if not executable.is_file():
        raise RuntimeError("Pinned uv executable is unavailable")
    result = subprocess.run(
        [str(executable), "--version"], capture_output=True, check=False, timeout=12
    )
    actual = result.stdout.decode("utf-8", errors="replace").strip()
    # uv emits a build hash and target triple after the version on some OSes.
    parts = actual.split()
    if result.returncode != 0 or parts[:2] not in (
        ["uv", required_version],
        ["uvx", required_version],
    ):
        raise RuntimeError("uvx version differs from the pinned release runtime")
    destination.mkdir(parents=True, exist_ok=True)
    filename = "uv.exe" if sys.platform == "win32" else "uv"
    target = destination / filename
    for candidate in (destination / "uv", destination / "uv.exe"):
        if candidate.exists() and candidate != target:
            candidate.unlink()
    shutil.copy2(executable, target)
    if os.name == "posix":
        target.chmod(0o755)
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    return filename, digest


def main() -> None:
    pin = tomllib.loads((ROOT / "uv.toml").read_text(encoding="utf-8"))["required-version"]
    binary = shutil.which("uv")
    if binary is None:
        raise RuntimeError("setup-uv must install pinned uv before GUI packaging")
    name, digest = stage(Path(binary), DEST, pin)
    print(f"Staged release bootstrap {name} uv={pin} sha256={digest}")


if __name__ == "__main__":
    main()
