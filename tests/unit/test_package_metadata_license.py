from pathlib import Path

import pytest

from scripts.check_package_metadata import _validate_metadata


def test_package_metadata_accepts_current_agpl_license() -> None:
    _validate_metadata(
        Path("bundle.whl"),
        "License: AGPL-3.0-only\nLicense-File: LICENSE\n",
        "AGPL-3.0-only",
    )


def test_package_metadata_rejects_stale_mit_metadata() -> None:
    with pytest.raises(ValueError, match="License: AGPL-3.0-only"):
        _validate_metadata(
            Path("bundle.whl"),
            "License: MIT\nLicense-File: LICENSE\n",
            "AGPL-3.0-only",
        )
