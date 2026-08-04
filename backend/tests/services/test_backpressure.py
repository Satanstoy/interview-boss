"""Tests for AdaptiveSemaphore back-pressure."""

from __future__ import annotations

import asyncio
import pytest


class TestAdaptiveSemaphore:
    def test_starts_at_initial_limit(self):
        from app.services.backpressure import AdaptiveSemaphore

        sem = AdaptiveSemaphore(initial=8, min_concurrency=2)
        assert sem.current_limit == 8

    def test_shrink_on_high_error_rate(self):
        from app.services.backpressure import AdaptiveSemaphore

        sem = AdaptiveSemaphore(
            initial=8,
            min_concurrency=2,
            window_seconds=60,
            error_threshold=0.3,
            grow_cooldown=0,
        )
        for _ in range(10):
            sem.record_success()
        for _ in range(4):
            sem.record_rate_limit_error()
        assert sem.current_limit == 8
        sem.record_rate_limit_error()
        assert sem.current_limit == 4

    def test_shrink_respects_minimum(self):
        from app.services.backpressure import AdaptiveSemaphore

        sem = AdaptiveSemaphore(initial=4, min_concurrency=2, grow_cooldown=0)
        for _ in range(10):
            sem.record_rate_limit_error()
        assert sem.current_limit == 2
        for _ in range(10):
            sem.record_rate_limit_error()
        assert sem.current_limit == 2

    def test_grow_on_low_error_rate(self):
        from app.services.backpressure import AdaptiveSemaphore

        sem = AdaptiveSemaphore(
            initial=8,
            min_concurrency=2,
            window_seconds=60,
            error_threshold=0.3,
            grow_cooldown=0,
        )
        for _ in range(10):
            sem.record_success()
        for _ in range(5):
            sem.record_rate_limit_error()
        assert sem.current_limit == 4
        for _ in range(25):
            sem.record_success()
        assert sem.current_limit > 4
        assert sem.current_limit <= 8

    def test_async_context_manager(self):
        from app.services.backpressure import AdaptiveSemaphore

        async def _test():
            sem = AdaptiveSemaphore(initial=2)
            async with sem:
                sem.record_success()
            return True

        assert asyncio.run(_test())

    def test_concurrent_acquisition(self):
        from app.services.backpressure import AdaptiveSemaphore

        async def _test():
            sem = AdaptiveSemaphore(initial=2)
            counter = {"val": 0}

            async def _worker():
                async with sem:
                    counter["val"] += 1
                    await asyncio.sleep(0.01)
                    sem.record_success()

            await asyncio.gather(*[_worker() for _ in range(6)])
            return counter["val"]

        assert asyncio.run(_test()) == 6
