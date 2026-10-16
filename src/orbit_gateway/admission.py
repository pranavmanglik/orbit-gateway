# Copyright 2026-present Orbit Contributors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Bound application concurrency with an opt-in Vegas-style latency controller."""

from __future__ import annotations

import math
from collections import deque
from statistics import median
from threading import Lock
from time import monotonic

from orbit.asgi import Request, Response
from orbit.asgi.middleware import NextHandler


class AdaptiveConcurrencyMiddleware:
    """Reject excess work and adjust a bounded in-process concurrency limit.

    The controller estimates queueing from observed request-handler duration relative to the
    minimum duration in a rolling sample window. These durations are application latency, not
    socket-level RTT. The limit is local to this process and should stay below Core's configured
    hard request cap. It does not replace edge proxy connection limits or distributed admission
    control.

    When the estimated queue is below ``alpha``, the limit grows additively. When it exceeds
    ``beta``, the limit falls proportionally toward the measured baseline. Updates happen once per
    completed observation window to avoid increasing the limit once per fast request.
    """

    def __init__(
        self,
        *,
        initial_limit: int = 64,
        minimum_limit: int = 1,
        maximum_limit: int = 1_024,
        alpha: float = 2.0,
        beta: float = 8.0,
        observation_window: int = 16,
        retry_after_seconds: int = 1,
    ) -> None:
        """Validate fixed control bounds before the middleware handles requests."""
        if (
            isinstance(minimum_limit, bool)
            or not isinstance(minimum_limit, int)
            or not 1 <= minimum_limit <= 1_000_000
            or isinstance(maximum_limit, bool)
            or not isinstance(maximum_limit, int)
            or not minimum_limit <= maximum_limit <= 1_000_000
            or isinstance(initial_limit, bool)
            or not isinstance(initial_limit, int)
            or not minimum_limit <= initial_limit <= maximum_limit
            or isinstance(alpha, bool)
            or not isinstance(alpha, (int, float))
            or not 0 <= alpha <= 1_000_000
            or isinstance(beta, bool)
            or not isinstance(beta, (int, float))
            or not alpha < beta <= 1_000_000
            or isinstance(observation_window, bool)
            or not isinstance(observation_window, int)
            or not 1 <= observation_window <= 4_096
            or isinstance(retry_after_seconds, bool)
            or not isinstance(retry_after_seconds, int)
            or not 1 <= retry_after_seconds <= 3_600
        ):
            raise ValueError("Adaptive concurrency policy values are invalid.")
        self._limit = initial_limit
        self._minimum_limit = minimum_limit
        self._maximum_limit = maximum_limit
        self._alpha = float(alpha)
        self._beta = float(beta)
        self._window_size = observation_window
        self._retry_after_seconds = retry_after_seconds
        self._active = 0
        self._completed = 0
        self._samples: deque[float] = deque(maxlen=min(256, max(8, observation_window * 4)))
        # These critical sections contain no awaits. A regular lock keeps the
        # process-local counters safe across worker threads without making
        # cancellation part of request cleanup.
        self._lock = Lock()

    @property
    def current_limit(self) -> int:
        """Return the latest in-process admission limit."""
        with self._lock:
            return self._limit

    @property
    def in_flight(self) -> int:
        """Return the number of requests currently inside the wrapped handler."""
        with self._lock:
            return self._active

    async def __call__(self, request: Request, next_handler: NextHandler) -> Response:
        """Admit within the current limit, then update the controller from handler latency."""
        with self._lock:
            if self._active >= self._limit:
                return Response.json(
                    {"code": "gateway.overloaded"},
                    status=503,
                    headers={"retry-after": str(self._retry_after_seconds)},
                )
            self._active += 1

        started = monotonic()
        try:
            return await next_handler(request)
        finally:
            duration = max(0.0, monotonic() - started)
            with self._lock:
                self._active -= 1
                self._samples.append(duration)
                self._completed += 1
                if self._completed >= self._window_size:
                    self._completed = 0
                    self._adjust_limit()

    def _adjust_limit(self) -> None:
        """Apply one bounded Vegas-style update using the current rolling latency sample."""
        if len(self._samples) < 2:
            return
        baseline = min(self._samples)
        observed = median(self._samples)
        if not math.isfinite(observed) or not math.isfinite(baseline) or observed <= 0:
            return
        if observed <= baseline:
            self._limit = min(self._maximum_limit, self._limit + 1)
            return
        estimated_queue = self._limit * (observed - baseline) / observed
        if estimated_queue < self._alpha:
            self._limit = min(self._maximum_limit, self._limit + 1)
        elif estimated_queue > self._beta:
            reduced = math.floor(self._limit * (baseline / observed))
            self._limit = max(self._minimum_limit, min(self._limit - 1, reduced))


__all__ = ["AdaptiveConcurrencyMiddleware"]
