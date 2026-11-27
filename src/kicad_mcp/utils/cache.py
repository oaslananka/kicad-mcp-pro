"""Small in-process TTL cache helpers for repeated read-only tool calls."""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from functools import wraps
from pathlib import Path
from typing import Any, cast

_MAX_CACHE_ENTRIES = 1024
_CACHE: OrderedDict[tuple[object, ...], tuple[float, Any]] = OrderedDict()
_CACHE_LOCK = threading.Lock()
_GENERATION = 0


def _freeze(value: object) -> object:
    if isinstance(value, dict):
        return tuple(sorted((str(key), _freeze(item)) for key, item in value.items()))
    if isinstance(value, set | frozenset):
        return frozenset(_freeze(item) for item in value)
    if isinstance(value, list | tuple):
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
                func,
                tuple(_freeze(arg) for arg in args),
                tuple(sorted((str(key), _freeze(value)) for key, value in kwargs.items())),
            )
            now = time.monotonic()
            with _CACHE_LOCK:
                generation = _GENERATION
                cached = _CACHE.get(key)
                if cached is not None and now - cached[0] < ttl_seconds:
                    _CACHE.move_to_end(key)
                    return cast(R, cached[1])
                _CACHE.pop(key, None)
            result = func(*args, **kwargs)
            with _CACHE_LOCK:
                if generation == _GENERATION:
                    _CACHE[key] = (now, result)
                    _CACHE.move_to_end(key)
                    while len(_CACHE) > _MAX_CACHE_ENTRIES:
                        _CACHE.popitem(last=False)
            return result

        return cast(Callable[P, R], wrapper)

    return decorator


def clear_ttl_cache() -> None:
    """Clear all cached TTL entries."""
    global _GENERATION
    with _CACHE_LOCK:
        _GENERATION += 1
        _CACHE.clear()
