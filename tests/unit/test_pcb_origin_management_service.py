from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from kicad_mcp.pcb.origin_management import PcbOriginService


class FakeConnectionError(Exception):
    pass


def _service(board: object, vectors: list[tuple[int, int]]) -> PcbOriginService:
    def vector_from_xy(x_nm: int, y_nm: int) -> object:
        vectors.append((x_nm, y_nm))
        return ("vector", x_nm, y_nm)

    return PcbOriginService(
        get_board=lambda: board,
        run_mutation=lambda _operation, command: command(),
        vector_from_xy=vector_from_xy,
        mm_to_nm=lambda value: int(round(value * 1_000_000)),
        coord_nm=lambda origin, axis: int(origin[axis]),  # type: ignore[index]
        nm_to_mm=lambda value: value / 1_000_000,
        connection_errors=(FakeConnectionError, OSError),
    )


def test_set_origin_preserves_conversion_and_success_message() -> None:
    vectors: list[tuple[int, int]] = []
    applied: list[object] = []
    service = _service(SimpleNamespace(set_origin=applied.append), vectors)

    assert service.set_origin(1.25, -2.5) == "Board origin set to (1.250, -2.500) mm."
    assert vectors == [(1_250_000, -2_500_000)]
    assert applied == [("vector", 1_250_000, -2_500_000)]


def test_get_origin_preserves_json_payload() -> None:
    service = _service(
        SimpleNamespace(get_origin=lambda: {"x": 2_500_000, "y": -750_000}),
        [],
    )

    assert json.loads(service.get_origin()) == {
        "origin_mm": {"x": 2.5, "y": -0.75},
        "source": "live-gui",
    }


@pytest.mark.parametrize(
    ("method", "args", "expected"),
    [
        (
            "set_origin",
            (1.0, 2.0),
            "Origin setting is not supported by the current KiCad IPC version.",
        ),
        (
            "get_origin",
            (),
            "Origin retrieval is not supported by the current KiCad IPC version.",
        ),
    ],
)
def test_unsupported_origin_operations_preserve_legacy_messages(
    method: str,
    args: tuple[float, ...],
    expected: str,
) -> None:
    service = _service(SimpleNamespace(), [])

    assert getattr(service, method)(*args) == expected


@pytest.mark.parametrize(
    ("method", "args", "expected"),
    [
        ("set_origin", (1.0, 2.0), "Failed to set origin: offline"),
        ("get_origin", (), "Failed to get origin: offline"),
    ],
)
def test_connection_errors_preserve_legacy_messages(
    method: str,
    args: tuple[float, ...],
    expected: str,
) -> None:
    def fail() -> object:
        raise FakeConnectionError("offline")

    service = PcbOriginService(
        get_board=fail,
        run_mutation=lambda _operation, command: command(),
        vector_from_xy=lambda x, y: (x, y),
        mm_to_nm=lambda value: int(value),
        coord_nm=lambda origin, axis: 0,
        nm_to_mm=float,
        connection_errors=(FakeConnectionError, OSError),
    )

    assert getattr(service, method)(*args) == expected


def test_unexpected_origin_errors_are_not_hidden() -> None:
    def fail() -> object:
        raise RuntimeError("bug")

    service = PcbOriginService(
        get_board=fail,
        run_mutation=lambda _operation, command: command(),
        vector_from_xy=lambda x, y: (x, y),
        mm_to_nm=lambda value: int(value),
        coord_nm=lambda origin, axis: 0,
        nm_to_mm=float,
        connection_errors=(FakeConnectionError, OSError),
    )

    with pytest.raises(RuntimeError, match="bug"):
        service.get_origin()
