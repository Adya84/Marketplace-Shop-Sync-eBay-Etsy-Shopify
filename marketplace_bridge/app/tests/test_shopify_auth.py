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
    assert "Version 0.0.22" in html
    assert "setInterval(refreshActivity,60000)" in html
    assert 'id="activity-rows"' in html
    assert "Refresh activity" in html


def test_product_set_identifier_is_a_separate_mutation_argument():
    from app.shopify import PRODUCT_SET

    assert "$identifier: ProductSetIdentifiers" in PRODUCT_SET
    assert "identifier: $identifier" in PRODUCT_SET
    assert '"identifier"' not in PRODUCT_SET


def test_inventory_mutations_include_required_idempotency_directive():
    from app.shopify import INVENTORY_ACTIVATE, INVENTORY_SET

    assert "@idempotent(key: $idempotencyKey)" in INVENTORY_ACTIVATE
    assert "@idempotent(key: $idempotencyKey)" in INVENTORY_SET


def test_inventory_quantities_include_required_compare_field():
    import inspect

    source = inspect.getsource(ShopifyClient._set_inventory)
    assert '"changeFromQuantity": current_available' in source
    assert 'quantity["name"] == "available"' in source
    assert "CURRENT_INVENTORY" in source


def test_dashboard_supports_bulk_draft_selection():
    html = render_dashboard([
        {"title": "Etsy item", "source": "etsy", "source_id": "123", "shopify_id": None},
    ], [], False, True, True)

    assert 'class="product-select"' in html
    assert "Create selected drafts" in html
    assert "api/products/shopify/bulk" in html


def test_dashboard_moves_linked_products_to_completed_section():
    html = render_dashboard([
        {"title": "Waiting", "source": "etsy", "source_id": "123", "shopify_id": None},
        {"title": "Sent", "source": "etsy", "source_id": "456", "shopify_id": "gid://shopify/Product/789"},
    ], [], False, True, True)

    ready_section, completed_section = html.split('<section class="card"><div class="hero"><h2>Completed</h2>', 1)
    assert "Ready to send" in ready_section
    assert "Waiting" in ready_section
    assert "Sent" not in ready_section
    assert "Sent" in completed_section
    assert "Completed" in completed_section
    assert "gid://shopify/Product/789" in completed_section


def test_completed_list_can_be_cleared_without_deleting_mappings():
    html = render_dashboard([
        {"title": "Sent", "source": "etsy", "source_id": "456", "shopify_id": "gid://shopify/Product/789", "completed_hidden": False},
        {"title": "Hidden", "source": "etsy", "source_id": "999", "shopify_id": "gid://shopify/Product/999", "completed_hidden": True},
    ], [], False, True, True)
    assert "Clear completed" in html
    assert "api/completed/clear" in html
    assert "Sent" in html
    assert "Hidden" not in html

