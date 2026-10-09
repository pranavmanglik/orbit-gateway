# Orbit Gateway

`orbit-gateway` provides optional HTTP middleware for Orbit's native ASGI runtime: explicit CORS
policy and bounded gzip response compression. For cloud-native edge routing, it also documents
NGINX Gateway Fabric deployment using Kubernetes Gateway API. Core retains the middleware
protocol, ASGI application, and middleware registration API; it does not bundle these policies or
an HTTP reverse-proxy server.

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

## Documentation

The package-specific guides cover [architecture](docs/architecture/overview.md), [operations and security](docs/operations/README.md), [NGINX Gateway Fabric deployment](docs/deployment/nginx-gateway-fabric.md), and [development](docs/development/README.md), with [security guidance](docs/security/overview.md). The [documentation index](docs/README.md) links to the full package overview and project policies.

## Development

The tests use `orbit-testing` to exercise the middleware through Core's ASGI protocol. In the Orbit
workspace, install that sibling package before the gateway's development extra:

```bash
python -m pip install -e ../orbit-core
python -m pip install -e ../orbit-testing
python -m pip install -e '.[dev]'
pytest
```

`orbit-testing` is a development-only dependency; applications using this middleware do not need
to install it.

## Status

This package is pre-alpha; its API is not stable and it is not yet a published release. It supports
Python 3.11 through 3.14.

Licensed under Apache-2.0.
