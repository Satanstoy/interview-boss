"""Adaptive concurrency limiter with rate-limit back-pressure.

Tracks recent LLM call errors and automatically reduces effective concurrency
when RateLimitError / 429 responses are detected. Concurrency recovers
gradually as error rate drops.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque

logger = logging.getLogger("interview-boss")


class AdaptiveSemaphore:
    """Semaphore that shrinks on rate-limit errors and grows back on success.

    Usage::

        sem = AdaptiveSemaphore(initial=8, min_concurrency=2)

        async with sem:
            result = await call_llm(...)
            sem.record_success()
    """

    def __init__(
        self,
        initial: int = 8,
        min_concurrency: int = 2,
        window_seconds: float = 60.0,
        error_threshold: float = 0.3,
        grow_cooldown: float = 10.0,
    ):
        self._max = initial
        self._min = min_concurrency
        self._current = initial
        self._window = window_seconds
        self._threshold = error_threshold
        self._grow_cooldown = grow_cooldown
        self._events: deque = deque()  # (timestamp, is_error)
        self._last_grow: float = 0.0
        self._last_shrink: float = 0.0
        self._lock = asyncio.Lock()
        self._sem = asyncio.Semaphore(initial)

    @property
    def current_limit(self) -> int:
        return self._current

    async def __aenter__(self):
        await self._sem.acquire()
        return self

    async def __aexit__(self, *args):
        self._sem.release()

    def record_success(self):
        self._events.append((time.monotonic(), False))
        self._maybe_grow()

    def record_rate_limit_error(self):
        self._events.append((time.monotonic(), True))
        self._maybe_shrink()

    def _prune(self):
        cutoff = time.monotonic() - self._window
        while self._events and self._events[0][0] < cutoff:
            self._events.popleft()

    def _error_rate(self) -> float:
        self._prune()
        if not self._events:
            return 0.0
        errors = sum(1 for _, is_err in self._events if is_err)
        return errors / len(self._events)

    def _maybe_shrink(self):
        rate = self._error_rate()
        now = time.monotonic()
        if (
            rate >= self._threshold
            and self._current > self._min
            and now - self._last_shrink >= self._grow_cooldown
        ):
            old = self._current
            self._current = max(self._min, self._current // 2)
            self._sem = asyncio.Semaphore(self._current)
            self._last_shrink = now
            logger.warning(
                "背压触发: 错误率 %.1f%% ≥ %.1f%%, 并发 %d → %d",
                rate * 100,
                self._threshold * 100,
                old,
                self._current,
            )

    def _maybe_grow(self):
        rate = self._error_rate()
        now = time.monotonic()
        if (
            rate < self._threshold * 0.5
            and self._current < self._max
            and now - self._last_grow >= self._grow_cooldown
        ):
            old = self._current
            self._current = min(self._max, self._current + 1)
            self._sem = asyncio.Semaphore(self._current)
            self._last_grow = now
            logger.info(
                "背压恢复: 错误率 %.1f%%, 并发 %d → %d",
                rate * 100,
                old,
                self._current,
            )


# Module-level singletons
matcher_semaphore = AdaptiveSemaphore(initial=8, min_concurrency=2)
compact_semaphore = AdaptiveSemaphore(initial=8, min_concurrency=2)
