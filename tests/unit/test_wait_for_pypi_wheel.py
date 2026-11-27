from __future__ import annotations

import json
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


def test_fetch_release_uses_verified_https_without_redirects() -> None:
    with patch.object(gate, "PoolManager") as create_pool:
        pool = create_pool.return_value
        response = pool.request.return_value.__enter__.return_value
        response.status = 200
        response.read.return_value = json.dumps(_payload()).encode()
        assert gate.fetch_release("4.24.0") == _payload()
        create_pool.assert_called_once_with(cert_reqs="CERT_REQUIRED", timeout=10.0)
        pool.request.assert_called_once_with(
            "GET",
            "https://pypi.org/pypi/kicad-mcp-pro/4.24.0/json",
            headers={"Accept": "application/json", "Accept-Encoding": "identity"},
            preload_content=False,
            redirect=False,
            retries=False,
            decode_content=False,
        )
        response.read.assert_called_once_with(gate.MAX_JSON_BYTES + 1)
        pool.clear.assert_called_once()


@pytest.mark.parametrize(
    "version", ["file:///etc/passwd", "../other", "4.24.0/other", "4.24.0-rc1"]
)
def test_fetch_rejects_invalid_version_before_connecting(version: str) -> None:
    with patch.object(gate, "PoolManager") as create_pool:
        with pytest.raises(ValueError, match="stable"):
            gate.fetch_release(version)
        create_pool.assert_not_called()


@pytest.mark.parametrize("status", [302, 404, 503])
def test_fetch_rejects_non_success_without_following_redirects(status: int) -> None:
    with patch.object(gate, "PoolManager") as create_pool:
        pool = create_pool.return_value
        response = pool.request.return_value.__enter__.return_value
        response.status = status
        with pytest.raises(OSError, match=str(status)):
            gate.fetch_release("4.24.0")
        pool.request.assert_called_once()
        response.read.assert_not_called()
        pool.clear.assert_called_once()


def test_fetch_rejects_oversized_json() -> None:
    with patch.object(gate, "PoolManager") as create_pool:
        pool = create_pool.return_value
        response = pool.request.return_value.__enter__.return_value
        response.status = 200
        response.read.return_value = b"x" * (gate.MAX_JSON_BYTES + 1)
        with pytest.raises(ValueError, match="size limit"):
            gate.fetch_release("4.24.0")
        pool.clear.assert_called_once()


def test_main_accepts_stable_version(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.argv", ["wait_for_pypi_wheel.py", "4.24.0"])
    with patch.object(gate, "wait_for_wheel", return_value=True) as wait:
        assert gate.main() == 0
        wait.assert_called_once_with("4.24.0")
