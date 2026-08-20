import pytest

from app.shopify import ShopifyClient


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


