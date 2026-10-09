from pathlib import Path

import yaml

MANIFEST = Path(__file__).parents[1] / "deploy/kubernetes/nginx-gateway-fabric.yaml"
POLICIES = (
    Path(__file__).parents[1] / "deploy/kubernetes/nginx-gateway-fabric-policies.example.yaml"
)
PAYMENT_ROUTE = (
    Path(__file__).parents[1] / "deploy/kubernetes/payment-webhook-http-route.example.yaml"
)


def test_nginx_gateway_fabric_example_terminates_tls_and_routes_to_core() -> None:
    resources = list(yaml.safe_load_all(MANIFEST.read_text(encoding="utf-8")))
    gateway, redirect, application = resources

    assert gateway["kind"] == "Gateway"
    assert gateway["spec"]["gatewayClassName"] == "nginx"
    listeners = {listener["name"]: listener for listener in gateway["spec"]["listeners"]}
    assert listeners["http"]["port"] == 80
    assert listeners["https"]["tls"]["mode"] == "Terminate"
    assert redirect["kind"] == "HTTPRoute"
    assert redirect["spec"]["rules"][0]["filters"][0]["requestRedirect"]["scheme"] == "https"
    assert redirect["spec"]["rules"][0]["filters"][0]["requestRedirect"]["statusCode"] == 308
    assert application["kind"] == "HTTPRoute"
    backend = application["spec"]["rules"][0]["backendRefs"][0]
    assert backend == {"name": "orbit-core", "port": 8000}


def test_optional_ngf_policies_scope_webhook_timeouts_and_upstream_keepalive() -> None:
    proxy_settings, upstream_settings, client_settings = yaml.safe_load_all(
        POLICIES.read_text(encoding="utf-8")
    )

    assert proxy_settings["kind"] == "ProxySettingsPolicy"
    assert proxy_settings["spec"]["targetRefs"][0]["name"] == "orbit-payment-webhooks"
    assert proxy_settings["spec"]["timeout"] == {
        "connect": "5s",
        "read": "30s",
        "send": "30s",
    }
    assert upstream_settings["kind"] == "UpstreamSettingsPolicy"
    assert upstream_settings["spec"]["targetRefs"][0]["name"] == "orbit-core"
    assert upstream_settings["spec"]["keepAlive"]["connections"] == 32
    assert client_settings["kind"] == "ClientSettingsPolicy"
    assert client_settings["spec"]["targetRef"]["name"] == "orbit-payment-webhooks"
    assert client_settings["spec"]["body"]["maxSize"] == "716800"


def test_payment_webhook_route_forwards_both_exact_paths_to_core() -> None:
    route = yaml.safe_load(PAYMENT_ROUTE.read_text(encoding="utf-8"))

    assert route["kind"] == "HTTPRoute"
    assert route["metadata"]["name"] == "orbit-payment-webhooks"
    assert route["spec"]["parentRefs"] == [{"name": "orbit-public", "sectionName": "https"}]
    assert [item["path"]["value"] for item in route["spec"]["rules"][0]["matches"]] == [
        "/webhooks/stripe",
        "/webhooks/razorpay",
    ]
    assert route["spec"]["rules"][0]["backendRefs"] == [{"name": "orbit-core", "port": 8000}]
