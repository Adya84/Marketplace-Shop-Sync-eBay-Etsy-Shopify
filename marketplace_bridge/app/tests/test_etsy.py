from app.etsy import EtsyClient


SAMPLE = {
    "listing_id": 123,
    "title": "Personalised sign",
    "description": "<p>Made to order</p>",
    "state": "active",
    "price": {"amount": 1299, "divisor": 100, "currency_code": "GBP"},
    "quantity": 4,
    "tags": ["sign"],
    "images": [{"rank": 1, "url_fullxfull": "https://example.com/sign.jpg"}],
    "inventory": {"products": [{
        "product_id": 456,
        "sku": "SIGN-RED",
        "property_values": [{"property_name": "Colour", "values": ["Red"]}],
        "offerings": [{"quantity": 3, "price": {"amount": 1499, "divisor": 100, "currency_code": "GBP"}}],
    }]},
}


def test_normalises_complete_etsy_listing():
    product = EtsyClient("key", "secret", "shop", "token")._normalise(SAMPLE)

    assert product.source == "etsy"
    assert product.description_html == "<p>Made to order</p>"
    assert product.images[0].url.endswith("sign.jpg")
    assert product.variants[0].sku == "SIGN-RED"
    assert product.variants[0].price == "14.99"
    assert product.variants[0].quantity == 3
    assert product.variants[0].options[0].value == "Red"


def test_authorised_user_id_comes_from_access_token():
    client = EtsyClient("key", "secret", "pending", "12345678.oauth-token")
    assert client.access_token.split(".", 1)[0] == "12345678"

