from __future__ import annotations

from unittest.mock import patch

import pytest

from scripts import wait_for_pypi_wheel as gate


def _payload(version: str = "4.24.0", *, yanked: bool = False, kind: str = "bdist_wheel") -> dict:
    return {
        "info": {"name": "kicad-mcp-pro", "version": version},
        "urls": [
            {
                "packagetype": kind,
                "yanked": yanked,
                "filename": "kicad_mcp_pro-4.24.0-py3-none-any.whl",
            }
        ],
    }


@pytest.mark.parametrize(
    "payload, expected",
    [
        (_payload(), True),
        (_payload(yanked=True), False),
        (_payload(version="4.23.0"), False),
        (_payload(kind="sdist"), False),
        ({"info": {"version": "4.24.0"}, "urls": []}, False),
        ({"info": None, "urls": []}, False),
    ],
)
def test_matching_wheel_gate(payload: dict, expected: bool) -> None:
    assert gate.has_matching_wheel(payload, "4.24.0") is expected


def test_wait_is_bounded_and_retries_unavailable_release() -> None:
    with patch.object(gate, "fetch_release", side_effect=[OSError("404"), _payload()]) as fetch:
        with patch.object(gate.time, "sleep") as sleep:
            assert gate.wait_for_wheel("4.24.0", attempts=2, delay=1)
            assert fetch.call_count == 2
            sleep.assert_called_once_with(1)
    with patch.object(gate, "fetch_release", return_value=_payload(yanked=True)) as fetch:
        with patch.object(gate.time, "sleep") as sleep:
            assert not gate.wait_for_wheel("4.24.0", attempts=2, delay=1)
            assert fetch.call_count == 2
            sleep.assert_called_once_with(1)
