from app.ebay import EbayClient


SAMPLE = '''<Item xmlns="urn:ebay:apis:eBLBaseComponents"><ItemID>123</ItemID><Title>Sample shirt</Title>
<Description><![CDATA[<p>Good shirt</p>]]></Description><Quantity>5</Quantity><SKU>SHIRT</SKU><StartPrice currencyID="GBP">12.99</StartPrice>
<PrimaryCategory><CategoryID>1</CategoryID><CategoryName>Shirts</CategoryName></PrimaryCategory>
<PictureDetails><PictureURL>https://example.com/one.jpg</PictureURL><PictureURL>https://example.com/two.jpg</PictureURL></PictureDetails>
<ItemSpecifics><NameValueList><Name>Brand</Name><Value>Example</Value></NameValueList></ItemSpecifics></Item>'''


def test_normalises_simple_listing():
    import xml.etree.ElementTree as ET
    product = EbayClient("token")._normalise(ET.fromstring(SAMPLE))
    assert product.source_id == "123"
    assert product.title == "Sample shirt"
    assert len(product.images) == 2
    assert product.variants[0].sku == "SHIRT"
    assert product.variants[0].quantity == 5
    assert product.vendor == "Example"


