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
"""Response compression and negotiation tests against Core's ASGI contract."""

import gzip

import pytest
from orbit import Application, ApplicationConfig
from orbit.asgi import ASGIApplication, Response
from orbit_testing import TestClient

from orbit_gateway import GZipMiddleware


def compose():
    app = Application(ApplicationConfig(name="gateway-tests"))
    return app, ASGIApplication(app)


@pytest.mark.asyncio
async def test_gzip_negotiates_and_skips_when_client_does_not_accept_it() -> None:
    app, asgi = compose()
    asgi.add_middleware(GZipMiddleware(minimum_size=1))

    @app.router.route("/text", name="text")
    async def text(request):
        return Response.text("compress me")

    async with TestClient(asgi) as client:
        compressed = await client.request("GET", "/text", headers={"accept-encoding": "gzip"})
        plain = await client.request("GET", "/text")
    assert gzip.decompress(compressed.body) == b"compress me"
    assert compressed.headers["content-encoding"] == "gzip"
    assert "content-encoding" not in plain.headers


def test_gzip_limits_are_immutable_and_strict() -> None:
    middleware = GZipMiddleware()
    with pytest.raises(AttributeError):
        middleware.minimum_size = 1  # type: ignore[misc]
    with pytest.raises(AttributeError):
        middleware.compresslevel = 1  # type: ignore[misc]
    with pytest.raises(ValueError, match="Compression limits"):
        GZipMiddleware(minimum_size=float("nan"))
    with pytest.raises(ValueError, match="Compression limits"):
        GZipMiddleware(compresslevel=True)


@pytest.mark.asyncio
async def test_gzip_quality_override_is_order_independent() -> None:
    app, asgi = compose()
    asgi.add_middleware(GZipMiddleware(minimum_size=1))

    @app.router.route("/text", name="text")
    async def text(request):
        return Response.text("compress me")

    async with TestClient(asgi) as client:
        disabled = await client.request(
            "GET", "/text", headers={"accept-encoding": "gzip;q=0, *;q=1"}
        )
        enabled = await client.request(
            "GET", "/text", headers={"accept-encoding": "*;q=1, gzip;q=1"}
        )
    assert "content-encoding" not in disabled.headers
    assert enabled.headers["content-encoding"] == "gzip"


@pytest.mark.parametrize(
    "header",
    (
        "gzip;Q=0",
        "gzip;q",
        "gzip;q;foo=bar",
        "gzip;q=1.0000",
        "gzip;q=0.5e0",
        "gzip;q=-0.1",
        "gzip;q=2",
        "gzip;q=0.",
    ),
)
def test_gzip_rejects_non_rfc_quality_values(header: str) -> None:
    assert not GZipMiddleware._accepts_gzip((header,))  # noqa: SLF001


@pytest.mark.asyncio
async def test_gzip_combines_repeated_fields_and_rejects_duplicates() -> None:
    app, asgi = compose()
    asgi.add_middleware(GZipMiddleware(minimum_size=1))

    @app.router.route("/text", name="text")
    async def text(request):
        return Response.text("compress me")

    async with TestClient(asgi) as client:
        combined = await client.request(
            "GET", "/text", headers=[("accept-encoding", "identity"), ("accept-encoding", "gzip")]
        )
        duplicate = await client.request(
            "GET", "/text", headers=[("accept-encoding", "gzip"), ("accept-encoding", "gzip")]
        )
    assert combined.headers["content-encoding"] == "gzip"
    assert "content-encoding" not in duplicate.headers


def test_gzip_negotiation_bounds_untrusted_headers() -> None:
    tokens = "gzip," + ",".join(f"encoding-{index}" for index in range(1_024))
    assert not GZipMiddleware._accepts_gzip((tokens,))  # noqa: SLF001
    assert not GZipMiddleware._accepts_gzip(("gzip," + "x" * (64 * 1024),))  # noqa: SLF001


@pytest.mark.asyncio
async def test_gzip_preserves_existing_vary_dimensions() -> None:
    app, asgi = compose()
    asgi.add_middleware(GZipMiddleware(minimum_size=1))

    @app.router.route("/text", name="text")
    async def text(request):
        return Response(
            body=b"compress me", headers={"content-type": "text/plain", "vary": "Origin"}
        )

    async with TestClient(asgi) as client:
        response = await client.request("GET", "/text", headers={"accept-encoding": "gzip"})
    assert response.headers["content-encoding"] == "gzip"
    assert response.headers["vary"] == "Origin, Accept-Encoding"


@pytest.mark.asyncio
async def test_gzip_does_not_transform_partial_content() -> None:
    app, asgi = compose()
    asgi.add_middleware(GZipMiddleware(minimum_size=1))

    @app.router.route("/partial", name="partial")
    async def partial(request):
        return Response(
            status=206,
            body=b"compress me",
            headers={"content-type": "text/plain", "content-range": "bytes 0-10/100"},
        )

    async with TestClient(asgi) as client:
        response = await client.request("GET", "/partial", headers={"accept-encoding": "gzip"})
    assert response.status == 206
    assert response.body == b"compress me"
    assert response.headers["content-range"] == "bytes 0-10/100"
    assert "content-encoding" not in response.headers
