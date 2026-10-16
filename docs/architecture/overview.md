# Orbit Gateway: architecture and boundaries

## Responsibility

`orbit-gateway` provides optional HTTP middleware for Orbit's native ASGI runtime: explicit CORS
policy, bounded gzip response compression, and adaptive in-process handler admission. Core retains the middleware protocol, ASGI
application, and middleware registration API; it does not bundle these policies. Kubernetes edge
routing is handled by a separately operated Gateway API implementation such as NGINX Gateway
Fabric, documented in the [deployment guide](../deployment/nginx-gateway-fabric.md).

```bash
pip install orbit-core orbit-gateway
```

```python
from orbit import Application, ApplicationConfig
from orbit.asgi import ASGIApplication
from orbit_gateway import CORSMiddleware, GZipMiddleware

app = Application(ApplicationConfig(name="example"))
asgi = ASGIApplication(app)
asgi.add_middleware(
    CORSMiddleware(
        allow_origins=("https://console.example",),
        allow_methods=("GET", "POST", "OPTIONS"),
        allow_headers=("content-type",),
    )
)
asgi.add_middleware(GZipMiddleware(minimum_size=500))
```

Middleware is opt-in and explicitly attached; importing or installing this package does not alter
an application's ASGI pipeline. Configure an exact origin allowlist for CORS. Wildcard origins
cannot be combined with credentials. Configured origins must be HTTP(S) origins without user-info,
path, query, or fragment components. Origin, method, and header policy collections are bounded to
1,024 entries and bounded text; malformed methods/headers are rejected during construction.
Duplicate request `Origin` and preflight policy fields fail closed. CORS-owned response fields are
replaced, while `Vary` dimensions are merged and deduplicated case-insensitively. Preflight
responses validate requested methods and headers and do not reflect untrusted values.

Gzip only affects eligible buffered text/JSON-like responses above the configured threshold. It
preserves existing `Vary` dimensions, skips streaming/already encoded bodies and partial/no-body
statuses, and removes stale `Content-Length`. `Accept-Encoding` quality values follow the HTTP
qvalue grammar; duplicate or malformed gzip/wildcard negotiation is rejected. Parsing is capped at
64 KiB and 1,024 tokens.

`AdaptiveConcurrencyMiddleware` uses a bounded rolling sample of handler durations and a
Vegas-style queue estimate to raise or lower an in-process admission limit. Handler duration is an
application-latency proxy, not TCP RTT or full network round-trip time. The limit is independent in
each worker, so set its maximum below Core's configured hard request cap and configure the edge
proxy separately. It returns a bounded JSON `503` with `Retry-After` when its current limit is full.
Core owns request draining after ASGI shutdown begins. Uvicorn or Gunicorn owns OS signal delivery
and worker lifecycle; this middleware does not install process signal handlers.

This Python package does not proxy arbitrary upstream requests or include NGINX binaries. A
Kubernetes Gateway and HTTPRoute route traffic from the NGINX Gateway Fabric data plane to the
Orbit Service. This keeps edge scaling, TLS termination, and service routing in the cluster's
networking layer. Mutual TLS between services, certificate issuance and rotation, and network
policy are owned by the selected ingress or service-mesh implementation; this package does not
provision identities or certificates.

## Declared dependencies

The following dependency declarations come from the checked-in manifests. Optional groups and development dependencies are called out separately.

### `pyproject.toml`
- `orbit-core>=0.1.0a1,<0.2`
- Optional `dev` group: `pytest>=8,<10`, `pytest-asyncio>=0.24,<2`, `ruff>=0.8,<1`, `mypy>=1.13,<2`, `orbit-testing>=0.1.0a1,<0.2`.

Declared dependencies do not mean that optional providers or services are bundled with this package.

## Implementation layout

Representative implementation files in this checkout:

- `src/orbit_gateway/__init__.py`
- `src/orbit_gateway/compression.py`
- `src/orbit_gateway/admission.py`
- `src/orbit_gateway/cors.py`

## Public contract and scope

## Status

This package is an unpublished v0.1.0-alpha review candidate. Its API may change before a stable
release. The declared support range is Python 3.11 through 3.14. Local checks do not substitute for
hosted CI or deployment validation.

Licensed under Apache-2.0.

## Boundary rules

Keep provider SDKs, credentials, transports, and provider-specific error translation in provider adapters. Keep reusable capability contracts in the matching capability package and lifecycle orchestration in Core. Apply the relevant layer for this repository and preserve the dependency direction shown above.
