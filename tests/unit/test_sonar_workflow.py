from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def test_sonar_cancels_superseded_runs_for_the_same_ref() -> None:
    workflow = yaml.safe_load(
        (ROOT / ".github" / "workflows" / "sonarcloud.yml").read_text(encoding="utf-8")
    )

    assert workflow["concurrency"] == {
        "group": "sonarcloud-${{ github.ref }}",
        "cancel-in-progress": True,
    }
