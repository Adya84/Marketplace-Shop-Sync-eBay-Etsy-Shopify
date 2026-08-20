import pytest

from app.shopify import ShopifyClient
from app.main import render_dashboard


def test_requires_myshopify_domain():
    with pytest.raises(ValueError, match="myshopify.com"):
        ShopifyClient("example.com", "2026-07", client_id="id", client_secret="secret")


def test_requires_credentials():
    with pytest.raises(ValueError, match="credentials"):
        ShopifyClient("store.myshopify.com", "2026-07")


def test_accepts_client_credentials():
    client = ShopifyClient("https://store.myshopify.com/", "2026-07", client_id="id", client_secret="secret")
    assert client.domain == "store.myshopify.com"
    assert client.token_endpoint == "https://store.myshopify.com/admin/oauth/access_token"


def test_dashboard_submits_connections_through_ingress_path():
    html = render_dashboard([], [], False, False, False)

    assert 'onsubmit="connect(event)"' in html
    assert "location.pathname.endsWith('/')" in html
    assert "fetch(endpoint(form.getAttribute('action'))" in html
    assert 'action="api/settings/shopify"' in html
    assert 'action="api/settings/ebay"' in html
    assert 'action="api/oauth/etsy/start"' in html
    assert 'action="api/oauth/etsy/finish"' in html


def test_product_set_identifier_is_a_separate_mutation_argument():
    from app.shopify import PRODUCT_SET

    assert "$identifier: ProductSetIdentifiers" in PRODUCT_SET
    assert "identifier: $identifier" in PRODUCT_SET
    assert '"identifier"' not in PRODUCT_SET


def test_inventory_mutations_include_required_idempotency_directive():
    from app.shopify import INVENTORY_ACTIVATE, INVENTORY_SET

    assert "@idempotent(key: $idempotencyKey)" in INVENTORY_ACTIVATE
    assert "@idempotent(key: $idempotencyKey)" in INVENTORY_SET


def test_dashboard_supports_bulk_draft_selection():
    html = render_dashboard([
        {"title": "Etsy item", "source": "etsy", "source_id": "123", "shopify_id": None},
    ], [], False, True, True)

    assert 'class="product-select"' in html
    assert "Create selected drafts" in html
    assert "api/products/shopify/bulk" in html
