from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Event

from kicad_mcp.utils import cache


def test_distinct_service_instances_do_not_share_cached_result() -> None:
    def make_reader(value: str):
        @cache.ttl_cache()
        def read() -> str:
            return value

        return read

    assert make_reader("board A")() == "board A"
    assert make_reader("board B")() == "board B"


def test_invalidated_inflight_read_cannot_repopulate_cache() -> None:
    started = Event()
    release = Event()
    current = "old"

    @cache.ttl_cache()
    def read() -> str:
        snapshot = current
        if snapshot == "old":
            started.set()
            assert release.wait(5)
        return snapshot

    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(read)
        try:
            assert started.wait(5)
            current = "new"
            cache.clear_ttl_cache()
        finally:
            release.set()
        assert pending.result(timeout=5) == "old"
    assert read() == "new"


def test_cache_has_bounded_capacity(monkeypatch) -> None:
    monkeypatch.setattr(cache, "_MAX_CACHE_ENTRIES", 3, raising=False)

    @cache.ttl_cache()
    def read(value: int) -> int:
        return value

    for index in range(10):
        assert read(index) == index
    assert len(cache._CACHE) <= 3
