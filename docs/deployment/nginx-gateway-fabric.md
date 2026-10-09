# NGINX Gateway Fabric deployment

Orbit keeps edge reverse proxying in the cluster networking layer. `orbit-gateway` does not
embed a proxy server or an NGINX binary; it ships this Gateway API reference for deployments that
choose NGINX Gateway Fabric (NGF), which uses NGINX as its data plane.

## Kubernetes controller choice

Use an actively maintained Gateway API implementation and pin its controller, chart, and image
versions through your deployment process. The community `kubernetes/ingress-nginx` controller was
retired in March 2026; new production deployments should not select it. NGINX Gateway Fabric is a
distinct NGINX project that implements Kubernetes Gateway API resources.

Install the Gateway API CRDs and NGF using the [official NGF installation guide](https://docs.nginx.com/nginx-gateway-fabric/install/). The example uses a method-preserving `308` redirect, so install an NGF release and Gateway API CRDs that support the extended `HTTPRoute308RedirectStatusCode` feature (NGF 2.5.0 or later).
The supplied manifest expects a `GatewayClass` named `nginx`, as created by the standard NGF
installation. Controller installation and CRD lifecycle are cluster-operator responsibilities.

## Apply the example

Edit [nginx-gateway-fabric.yaml](../../deploy/kubernetes/nginx-gateway-fabric.yaml) before use:

- Replace `app.example.com` with the application hostname.
- Provision `app-example-com-tls` as a TLS Secret in the `orbit` namespace, or adapt the Gateway
  to your certificate controller and namespace policy.
- Ensure the `orbit-core` Service exposes port `8000` in that namespace; change the backend name
  and port to match the deployment.
- Apply the manifest only after the Gateway API CRDs and NGF controller are installed.

The example permanently redirects HTTP to HTTPS with `308` so clients preserve methods such as
`POST`, and routes HTTPS requests to the Core Service. It is a
starting point, not a complete cluster policy. Configure cloud load balancers, static addresses,
DNS, certificate renewal, network policies, resource requests/limits, access logs, rate limits,
request-body bounds, and trusted client-address handling for the actual environment. Do not trust
client-supplied `Forwarded` or `X-Forwarded-*` headers; configure the controller and Core's trusted
proxy settings to match the known network hops.

## Payment webhook routes, upstream timeouts, and keepalive

The optional [payment webhook HTTPRoute](../../deploy/kubernetes/payment-webhook-http-route.example.yaml)
forwards `/webhooks/stripe` and `/webhooks/razorpay` to the Orbit Core Service. Keep those exact
paths aligned with the application router. Use
[nginx-gateway-fabric-policies.example.yaml](../../deploy/kubernetes/nginx-gateway-fabric-policies.example.yaml)
as an NGF-specific starting point. Its
`ProxySettingsPolicy` uses 5 seconds to connect and 30 seconds between upstream reads/writes. These
are idle timeouts, not total transaction deadlines. Measure provider delivery deadlines and app
processing time, then set values that fit the service SLO. NGF currently ignores `HTTPRoute` rule
`timeouts`, so use `ProxySettingsPolicy` for upstream proxy timeouts.

The sample `ClientSettingsPolicy` limits webhook request bodies to 716,800 bytes (700 KiB), matching
`PaymentWebhookIngress`. Keep the application limit, NGINX limit, and provider route configuration
aligned; NGF rejects oversized payloads at the edge with 413 before they reach Core.

The sample `UpstreamSettingsPolicy` keeps 32 idle upstream connections per NGINX worker, matching
the documented NGINX default. Tune based on measured concurrency, worker count, file-descriptor
limits, and Core capacity; more idle sockets are not automatically faster. Payment webhook handlers
verify the raw body, publish to the durable RabbitMQ work queue, and return success only after a
publisher confirmation. A broker failure returns a retryable server error. Separate workers perform
payment/database processing. Deduplicate verified events by provider, account, and
`VerifiedWebhook.event_id` in the same transaction as payment state. Do not enable proxy retries for
payment POST requests without a provider-specific idempotency and replay analysis.

## Client IP forwarding

NGF’s default forwarded headers are not a substitute for a trusted-proxy policy. Configure the
Gateway’s `NginxProxy` resource with `rewriteClientIP.mode: XForwardedFor` and only the exact
load-balancer CIDRs in `trustedAddresses` when that load balancer supplies a trusted
`X-Forwarded-For` chain. Enable recursive selection only when the proxy chain is understood. Never
trust `0.0.0.0/0` or arbitrary client-supplied forwarding headers. Set the NGINX data-plane Service
to `externalTrafficPolicy: Local` only when the cloud load balancer supports node-local endpoints
and its health checks and traffic distribution are configured accordingly; it can preserve the
source address but may drop traffic on nodes without a local data-plane pod. Then configure Core to
trust only the Gateway data-plane network as a proxy. Validate the observed client address using
requests through the real load-balancer path before applying IP-based controls.

The relevant fields on the `NginxProxy` resource attached to the `GatewayClass` are:

```yaml
spec:
  kubernetes:
    service:
      externalTrafficPolicy: Local
  rewriteClientIP:
    mode: XForwardedFor
    setIPRecursively: true
    trustedAddresses:
      - type: CIDR
        value: "REPLACE_WITH_LOAD_BALANCER_CIDR"
```

Merge these settings into the controller’s existing referenced `NginxProxy` configuration; do not
create an unattached resource or replace the controller’s install-managed defaults blindly.

For HTTP/2 or HTTP/3, verify the selected NGF release, Gateway listener, cloud load balancer, and
client protocol support independently. The manifest does not claim HTTP/3 enablement.

NGF reconciles Gateway and HTTPRoute resources to create NGINX data-plane resources. Scale and
secure that controller/data plane independently from the Orbit application. Kubernetes Gateway
API is the portable routing contract; NGINX-specific behavior should remain an explicit deployment
choice.

## Verify

After applying, inspect controller status and conditions:

```bash
kubectl get gatewayclass nginx
kubectl get gateway orbit-public -n orbit -o yaml
kubectl get httproute -n orbit -o yaml
```

Confirm `Accepted` and `Programmed` conditions are true, TLS is served with the expected
certificate, plain HTTP redirects to HTTPS, and the application path reaches the intended Service.
This repository does not claim a live Kubernetes, cloud load balancer, DNS, certificate, or NGF
acceptance run.
