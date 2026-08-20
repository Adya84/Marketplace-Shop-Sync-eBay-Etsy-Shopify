import hashlib
import hmac

from app.tiktok import TikTokShopClient


def test_signature_matches_documented_algorithm():
    client = TikTokShopClient("123456", "abc000def111", "token", "shop")
    params = {"app_key": "123456", "timestamp": 1234567890}
    message = "abc000def111/authorization/202309/shopsapp_key123456timestamp1234567890abc000def111"
    expected = hmac.new(b"abc000def111", message.encode(), hashlib.sha256).hexdigest()
    assert client.generate_sign("/authorization/202309/shops", params) == expected


def test_normalises_images_variants_options_and_stock():
    product = TikTokShopClient.normalise({
        "id": "product-1", "title": "Personalised Bottle", "description": "Line one\nLine two",
        "status": "ACTIVATE", "main_images": [{"urls": ["https://img/one.jpg"]}],
        "category_chains": [{"id": "12", "local_name": "Drinkware"}],
        "skus": [{
            "id": "sku-1", "seller_sku": "BOTTLE-BLUE",
            "price": {"tax_exclusive_price": "12.99", "currency": "GBP"},
            "inventory": [{"quantity": 3}, {"quantity": 2}],
            "sales_attributes": [{"name": "Colour", "value_name": "Blue",
                                  "sku_img": {"urls": ["https://img/blue.jpg"]}}],
        }],
    })
    assert product.source == "tiktok"
    assert product.images[0].url == "https://img/one.jpg"
    assert product.variants[0].quantity == 5
    assert product.variants[0].options[0].value == "Blue"
    assert product.variants[0].image_url == "https://img/blue.jpg"
    assert product.category_name == "Drinkware"
    assert product.description_html == "<p>Line one<br>Line two</p>"

