"""Stage the pinned uv runtime into a Tauri release bundle.

Only release builds call this; no global installs, no downloads, and no
repository-owned binaries. The setup-uv Action provides the pinned executable.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "src-tauri" / "resources" / "bootstrap"


def stage(executable: Path, destination: Path) -> tuple[str, str]:
    """Copy the setup-uv executable; release CI verifies its exact version first.

    This stage is intentionally file-only. No arbitrary binary is executed by
    the Python packaging helper. The pinned setup-uv Action and the explicit
    version gate in gui-release.yml are mandatory before this runs.
    """
    if not executable.is_file():
        raise RuntimeError("Pinned uv executable is unavailable")
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
    name, digest = stage(Path(binary), DEST)
    print(f"Staged release bootstrap {name} required_uv={pin} sha256={digest}")


if __name__ == "__main__":
    main()
