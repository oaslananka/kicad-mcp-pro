from __future__ import annotations

import pytest

from scripts import workflow_security


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("unknown", "unknown"),
        ("informational", "informational"),
        ("low", "low"),
        ("medium", "medium"),
        ("high", "high"),
    ],
)
def test_canonical_min_severity_maps_allowlisted_values_to_literals(
    value: str, expected: str
) -> None:
    assert workflow_security._canonical_min_severity(value) == expected


def test_canonical_min_severity_rejects_unknown_value() -> None:
    with pytest.raises(ValueError, match="Unsupported zizmor minimum severity"):
        workflow_security._canonical_min_severity("critical")


def test_main_runs_zizmor_with_canonical_severity(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    calls: list[list[str]] = []

    monkeypatch.setattr(workflow_security.shutil, "which", lambda command: "/tools/zizmor")
    monkeypatch.setattr(
        workflow_security.subprocess,
        "run",
        lambda command, check=False: (
            calls.append(command) or workflow_security.subprocess.CompletedProcess(command, 0)
        ),
    )
    monkeypatch.setattr(
        workflow_security.sys,
        "argv",
        ["workflow_security.py", "--min-severity", "high"],
    )

    with pytest.raises(SystemExit) as exc:
        workflow_security.main()

    assert exc.value.code == 0
    assert calls == [
        [
            "/tools/zizmor",
            "--offline",
            "--min-severity",
            "high",
            str(workflow_security.REPO_ROOT / ".github" / "workflows"),
        ]
    ]
