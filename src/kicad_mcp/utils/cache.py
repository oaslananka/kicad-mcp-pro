"""Small in-process TTL cache helpers for repeated read-only tool calls."""

from __future__ import annotations

import time
from collections.abc import Callable
from functools import wraps
from pathlib import Path
from typing import Any, cast

_CACHE: dict[tuple[object, ...], tuple[float, Any]] = {}


def _freeze(value: object) -> object:
    if isinstance(value, dict):
        return tuple(sorted((str(key), _freeze(item)) for key, item in value.items()))
    if isinstance(value, list | tuple | set | frozenset):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, Path):
        return str(value)
    try:
        hash(value)
    except TypeError:
        return repr(value)
    return value


def ttl_cache[**P, R](ttl_seconds: int = 5) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Cache a function result for a small, fixed amount of time."""

    def decorator(func: Callable[P, R]) -> Callable[P, R]:
        @wraps(func)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            key = (
                func.__module__,
                func.__name__,
                tuple(_freeze(arg) for arg in args),
                tuple(sorted((str(key), _freeze(value)) for key, value in kwargs.items())),
            )
            now = time.time()
            cached = _CACHE.get(key)
            if cached is not None and now - cached[0] < ttl_seconds:
                return cast(R, cached[1])
            result = func(*args, **kwargs)
            _CACHE[key] = (now, result)
            return result

        return cast(Callable[P, R], wrapper)

    return decorator


def clear_ttl_cache() -> None:
    """Clear all cached TTL entries."""
    _CACHE.clear()
