from __future__ import annotations

import html
import xml.etree.ElementTree as ET
from decimal import Decimal

import httpx

from .models import Image, OptionValue, Product, Variant

NS = {"e": "urn:ebay:apis:eBLBaseComponents"}


def _text(node, path: str, default=""):
    found = node.find(path, NS)
    return found.text.strip() if found is not None and found.text else default


class EbayListingUnavailable(RuntimeError):
    """Raised when an item returned by the seller list can no longer be read."""


_UNAVAILABLE_MESSAGES = (
    "this listing was removed",
    "listing was removed",
    "intellectual property rights owner",
    "item has been removed",
    "item is no longer available",
    "listing is no longer available",
    "invalid item",
    "item not found",
)


def is_unavailable_listing_error(message: str) -> bool:
    value = str(message or "").strip().lower()
    return any(fragment in value for fragment in _UNAVAILABLE_MESSAGES)


class EbayClient:
    """Reads the seller's complete active inventory through eBay Trading API.

    Trading API is used because it includes listings created through both the
    website and APIs; Inventory API alone does not expose every legacy listing.
    """

    def __init__(self, access_token: str, environment="production", site_id="3"):
        self.access_token = access_token
        self.endpoint = "https://api.ebay.com/ws/api.dll" if environment == "production" else "https://api.sandbox.ebay.com/ws/api.dll"
        self.site_id = site_id

    async def _call(self, name: str, body: str) -> ET.Element:
        headers = {
            "X-EBAY-API-CALL-NAME": name,
            "X-EBAY-API-COMPATIBILITY-LEVEL": "1423",
            "X-EBAY-API-SITEID": self.site_id,
            "X-EBAY-API-IAF-TOKEN": self.access_token,
            "Content-Type": "text/xml",
        }
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(self.endpoint, content=body.encode(), headers=headers)
            response.raise_for_status()
        root = ET.fromstring(response.content)
        ack = _text(root, "e:Ack")
        if ack not in {"Success", "Warning"}:
            message = _text(root, ".//e:LongMessage", _text(root, ".//e:ShortMessage", "Unknown eBay error"))
            raise RuntimeError(message)
        return root

    async def list_active_ids(self) -> list[str]:
        ids: list[str] = []
        page = 1
        while True:
            body = f'''<?xml version="1.0" encoding="utf-8"?>
            <GetMyeBaySellingRequest xmlns="urn:ebay:apis:eBLBaseComponents">
              <ActiveList><Include>true</Include><Pagination><EntriesPerPage>200</EntriesPerPage><PageNumber>{page}</PageNumber></Pagination></ActiveList>
              <DetailLevel>ReturnSummary</DetailLevel>
            </GetMyeBaySellingRequest>'''
            root = await self._call("GetMyeBaySelling", body)
            ids.extend(_text(item, "e:ItemID") for item in root.findall(".//e:ActiveList/e:ItemArray/e:Item", NS))
            total = int(_text(root, ".//e:ActiveList/e:PaginationResult/e:TotalNumberOfPages", "1"))
            if page >= total:
                return [item_id for item_id in ids if item_id]
            page += 1

    async def get_product(self, item_id: str) -> Product:
        body = f'''<?xml version="1.0" encoding="utf-8"?>
        <GetItemRequest xmlns="urn:ebay:apis:eBLBaseComponents">
          <ItemID>{html.escape(item_id)}</ItemID><DetailLevel>ReturnAll</DetailLevel><IncludeItemSpecifics>true</IncludeItemSpecifics>
        </GetItemRequest>'''
        try:
            root = await self._call("GetItem", body)
        except RuntimeError as exc:
            if is_unavailable_listing_error(str(exc)):
                raise EbayListingUnavailable(str(exc)) from exc
            raise
        item = root.find("e:Item", NS)
        if item is None:
            raise EbayListingUnavailable(f"eBay returned no item for {item_id}")
        return self._normalise(item)

    def _normalise(self, item: ET.Element) -> Product:
        item_id = _text(item, "e:ItemID")
        currency = "GBP"
        price_node = item.find("e:SellingStatus/e:CurrentPrice", NS)
        if price_node is None:
            price_node = item.find("e:StartPrice", NS)
        price = price_node.text if price_node is not None and price_node.text else "0.00"
        if price_node is not None:
            currency = price_node.attrib.get("currencyID", currency)

        picture_urls = [_text(n, ".") for n in item.findall("e:PictureDetails/e:PictureURL", NS)]
        images = [Image(url=url, position=i + 1) for i, url in enumerate(dict.fromkeys(picture_urls)) if url]
        attributes = {}
        for spec in item.findall("e:ItemSpecifics/e:NameValueList", NS):
            name = _text(spec, "e:Name")
            values = [_text(v, ".") for v in spec.findall("e:Value", NS)]
            if name:
                attributes[name] = ", ".join(filter(None, values))

        variants = []
        for index, variation in enumerate(item.findall("e:Variations/e:Variation", NS)):
            options = []
            for choice in variation.findall("e:VariationSpecifics/e:NameValueList", NS):
                options.append(OptionValue(_text(choice, "e:Name"), _text(choice, "e:Value")))
            sku = _text(variation, "e:SKU") or f"EBAY-{item_id}-{index + 1}"
            listed_quantity = int(_text(variation, "e:Quantity", "0"))
            sold_quantity = int(_text(variation, "e:SellingStatus/e:QuantitySold", "0"))
            quantity = max(0, listed_quantity - sold_quantity)
            variants.append(Variant(
                source_id=sku, sku=sku, price=_text(variation, "e:StartPrice", price), quantity=quantity, options=options
            ))
        if not variants:
            # QuantityAvailable is the clearest remaining-stock field for normal
            # fixed-price listings when eBay returns it. Fall back to the documented
            # Quantity - QuantitySold calculation for listings where it is absent.
            quantity_available = _text(item, "e:QuantityAvailable", "")
            if quantity_available != "":
                quantity = max(0, int(quantity_available))
            else:
                listed_quantity = int(_text(item, "e:Quantity", "0"))
                sold_quantity = int(_text(item, "e:SellingStatus/e:QuantitySold", "0"))
                quantity = max(0, listed_quantity - sold_quantity)
            sku = _text(item, "e:SKU") or f"EBAY-{item_id}"
            variants = [Variant(source_id=sku, sku=sku, price=str(Decimal(price)), quantity=quantity)]

        for picture_set in item.findall("e:Variations/e:Pictures/e:VariationSpecificPictureSet", NS):
            value = _text(picture_set, "e:VariationSpecificValue")
            url = _text(picture_set, "e:PictureURL")
            matching_skus = [v.sku for v in variants if any(o.value == value for o in v.options)]
            if url:
                existing = next((image for image in images if image.url == url), None)
                if existing:
                    existing.variant_skus.extend(matching_skus)
                else:
                    images.append(Image(url=url, position=len(images) + 1, variant_skus=matching_skus))
                for variant in variants:
                    if variant.sku in matching_skus:
                        variant.image_url = url

        return Product(
            source="ebay", source_id=item_id, title=_text(item, "e:Title"),
            description_html=_text(item, "e:Description"), status="active", currency=currency,
            vendor=attributes.get("Brand", ""), product_type=_text(item, "e:PrimaryCategory/e:CategoryName"),
            category_id=_text(item, "e:PrimaryCategory/e:CategoryID"),
            category_name=_text(item, "e:PrimaryCategory/e:CategoryName"),
            tags=[f"eBay category: {_text(item, 'e:PrimaryCategory/e:CategoryName')}", f"eBay item: {item_id}"],
            images=images, variants=variants, attributes=attributes,
            source_url=f"https://www.ebay.co.uk/itm/{item_id}",
        )
