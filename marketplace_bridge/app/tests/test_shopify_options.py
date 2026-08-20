from app.shopify import ShopifyClient


def test_simple_variant_gets_required_default_option():
    options, variants = ShopifyClient._product_options_and_variants([
        {"sku": "SIMPLE", "price": "4.99", "quantity": 1, "options": []},
    ])
    assert options == [{
        "name": "Title", "position": 1, "values": [{"name": "Default Title"}],
    }]
    assert variants[0]["optionValues"] == [
        {"optionName": "Title", "name": "Default Title"},
    ]


def test_every_variant_gets_every_product_option():
    options, variants = ShopifyClient._product_options_and_variants([
        {"sku": "RED-S", "price": "4.99", "options": [
            {"name": "Colour", "value": "Red"}, {"name": "Size", "value": "Small"},
        ]},
        {"sku": "BLUE", "price": "5.99", "options": [
            {"name": "Colour", "value": "Blue"},
        ]},
    ])
    assert [option["name"] for option in options] == ["Colour", "Size"]
    assert variants[1]["optionValues"] == [
        {"optionName": "Colour", "name": "Blue"},
        {"optionName": "Size", "name": "Default"},
    ]

