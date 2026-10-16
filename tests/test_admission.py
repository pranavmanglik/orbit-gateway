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
"""Admission control tests for concurrency bounds and latency adaptation."""

import asyncio

import pytest
from orbit.asgi import Request, Response

from orbit_gateway import AdaptiveConcurrencyMiddleware


def test_policy_bounds_are_validated() -> None:
    with pytest.raises(ValueError, match="policy"):
        AdaptiveConcurrencyMiddleware(initial_limit=0)
    with pytest.raises(ValueError, match="policy"):
        AdaptiveConcurrencyMiddleware(maximum_limit=10**400)
    with pytest.raises(ValueError, match="policy"):
        AdaptiveConcurrencyMiddleware(alpha=float("nan"))
    with pytest.raises(ValueError, match="policy"):
        AdaptiveConcurrencyMiddleware(alpha=4, beta=4)


@pytest.mark.asyncio
async def test_capacity_rejects_fast_and_releases_after_completion() -> None:
    middleware = AdaptiveConcurrencyMiddleware(
        initial_limit=1,
        minimum_limit=1,
        maximum_limit=1,
    )
    entered = asyncio.Event()
    release = asyncio.Event()

    async def slow_handler(request: Request) -> Response:
        entered.set()
        await release.wait()
        return Response.text("done")

    request = Request("GET", "/slow")
    active = asyncio.create_task(middleware(request, slow_handler))
    await entered.wait()

    rejected = await middleware(request, slow_handler)
    assert rejected.status == 503
    assert rejected.headers["retry-after"] == "1"
    assert middleware.in_flight == 1

    release.set()
    assert (await active).body == b"done"
    assert middleware.in_flight == 0


@pytest.mark.asyncio
async def test_vegas_controller_increases_and_reduces_with_latency(monkeypatch) -> None:
    clock = iter((0.0, 0.001, 0.001, 0.002, 0.002, 0.102, 0.102, 0.202))
    monkeypatch.setattr("orbit_gateway.admission.monotonic", lambda: next(clock))
    middleware = AdaptiveConcurrencyMiddleware(
        initial_limit=4,
        minimum_limit=1,
        maximum_limit=8,
        alpha=0.25,
        beta=0.5,
        observation_window=2,
    )
    request = Request("GET", "/sample")

    async def handler(request: Request) -> Response:
        return Response.text("ok")

    await middleware(request, handler)
    await middleware(request, handler)
    assert middleware.current_limit == 5

    await middleware(request, handler)
    await middleware(request, handler)
    assert middleware.current_limit == 1


@pytest.mark.asyncio
async def test_cancellation_releases_admitted_capacity() -> None:
    middleware = AdaptiveConcurrencyMiddleware(initial_limit=1, maximum_limit=1)
    entered = asyncio.Event()

    async def handler(request: Request) -> Response:
        entered.set()
        await asyncio.Event().wait()
        return Response.text("unreachable")

    task = asyncio.create_task(middleware(Request("GET", "/cancel"), handler))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert middleware.in_flight == 0
