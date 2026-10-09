# Orbit Gateway: operations and security

This guide organizes runtime behavior documented by the package. It does not certify production readiness. Verify provider/client versions, permissions, transport security, limits, and failure behavior in the target environment before release.

For Kubernetes edge traffic, operate NGINX Gateway Fabric or another Gateway API controller
separately from Orbit. Use the [NGF deployment guide](../deployment/nginx-gateway-fabric.md) as a
starting point. `orbit-gateway` itself only adds in-process CORS and gzip middleware.

## Configuration surface

Environment names found in the package README:

The package README does not name `ORBIT_*` variables. Use its typed constructors and application configuration, and confirm exact runtime inputs in the implementation before deployment.

Use the package README's constructor and deployment examples. Store credentials in a secret manager and avoid logging credentials, raw provider errors, request data, or opaque cursors.

## Lifecycle, failure behavior, and limits

`orbit-gateway` provides optional HTTP middleware for Orbit's native ASGI runtime: explicit CORS
policy and bounded gzip response compression. Core retains the middleware protocol, ASGI
application, and middleware registration API; it does not bundle these policies.

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

## Status

This package is pre-alpha; its API is not stable and it is not yet a published release. It supports
Python 3.11 through 3.14.

Licensed under Apache-2.0.

## Production validation

Validate startup/shutdown cleanup, timeout and cancellation behavior, concurrency and payload bounds where applicable, secret rotation and least-privilege access, data durability, backup/restore, and failover against the selected provider. Do not infer distributed or durable guarantees from an in-process API or fake-client tests.
