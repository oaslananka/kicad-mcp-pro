from __future__ import annotations

from pathlib import Path

import pytest

from scripts.runtime_path_safety import REPO_ROOT, approved_runtime_path


def test_approved_runtime_path_allows_repo_and_temp_and_blocks_home(tmp_path: Path) -> None:
    assert approved_runtime_path(REPO_ROOT / "server.json") == (REPO_ROOT / "server.json").resolve()
    assert (
        approved_runtime_path(tmp_path / "artifact.json") == (tmp_path / "artifact.json").resolve()
    )

    with pytest.raises(ValueError, match="outside approved automation roots"):
        approved_runtime_path(Path.home() / ".ssh" / "id_rsa")


def test_approved_runtime_path_accepts_exact_explicit_trusted_path() -> None:
    trusted = Path.home() / ".github-output-test"

    assert approved_runtime_path(trusted, extra_roots=(trusted,)) == trusted.resolve()
