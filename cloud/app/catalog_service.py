from __future__ import annotations

import html as html_lib
import json
import uuid
import xml.etree.ElementTree as ET
from decimal import Decimal

import httpx
from sqlalchemy import select

from .db import SessionLocal
from .marketplace_oauth import BrokerClient
from .models import CatalogProduct, ListingMapping, SyncJob

NS = {"e": "urn:ebay:apis:eBLBaseComponents"}
SHOPIFY_API_VERSION = "2026-07"

SHOPIFY_PRODUCTS_QUERY = """
query ShopSyncProducts($cursor: String) {
  products(first: 50, after: $cursor) {
    pageInfo { hasNextPage endCursor }
    nodes {
      id legacyResourceId title descriptionHtml status vendor productType tags handle
      media(first: 100) { nodes { preview { image { url altText } } } }
      variants(first: 250) {
        nodes { id legacyResourceId title sku barcode price inventoryQuantity selectedOptions { name value } image { url altText } }
      }
    }
  }
}
"""

PRODUCT_SET = """
mutation ProductSet($input: ProductSetInput!, $identifier: ProductSetIdentifiers, $synchronous: Boolean!) {
  productSet(input: $input, identifier: $identifier, synchronous: $synchronous) {
    product { id title status variants(first: 250) { nodes { id sku inventoryItem { id } } } }
    userErrors { field message code }
  }
}
"""

PRODUCT_CREATE_MEDIA = """
mutation CreateMedia($productId: ID!, $media: [CreateMediaInput!]!) {
  productCreateMedia(productId: $productId, media: $media) {
    media { id status alt mediaContentType }
    mediaUserErrors { field message code }
  }
}
"""

INVENTORY_ACTIVATE = """
mutation Activate($inventoryItemId: ID!, $locationId: ID!, $idempotencyKey: String!) {
  inventoryActivate(inventoryItemId: $inventoryItemId, locationId: $locationId) @idempotent(key: $idempotencyKey) {
    inventoryLevel { id quantities(names: ["available"]) { name quantity } }
    userErrors { field message }
  }
}
"""

CURRENT_INVENTORY = """
query CurrentInventory($inventoryItemId: ID!, $locationId: ID!) {
  inventoryItem(id: $inventoryItemId) {
    inventoryLevel(locationId: $locationId) { quantities(names: ["available"]) { name quantity } }
  }
}
"""

INVENTORY_SET = """
mutation SetInventory($input: InventorySetQuantitiesInput!, $idempotencyKey: String!) {
  inventorySetQuantities(input: $input) @idempotent(key: $idempotencyKey) {
    inventoryAdjustmentGroup { createdAt }
    userErrors { field message code }
  }
}
"""

LOCATION_QUERY = "{ locations(first: 1) { nodes { id name } } }"


def save_product(workspace_id: str, product: dict) -> None:
    with SessionLocal() as db:
        row = db.scalar(select(CatalogProduct).where(
            CatalogProduct.workspace_id == workspace_id,
            CatalogProduct.source == str(product["source"]),
            CatalogProduct.source_id == str(product["source_id"]),
        ))
        if not row:
            row = CatalogProduct(workspace_id=workspace_id, source=str(product["source"]), source_id=str(product["source_id"]))
            db.add(row)
        row.title = str(product.get("title") or "")[:512]
        row.payload = json.dumps(product, separators=(",", ":"))
        db.commit()


def get_product(workspace_id: str, source: str, source_id: str) -> dict | None:
    with SessionLocal() as db:
        row = db.scalar(select(CatalogProduct).where(CatalogProduct.workspace_id == workspace_id, CatalogProduct.source == source, CatalogProduct.source_id == source_id))
        return json.loads(row.payload) if row else None


def list_products(workspace_id: str) -> list[dict]:
    with SessionLocal() as db:
        rows = db.scalars(select(CatalogProduct).where(CatalogProduct.workspace_id == workspace_id).order_by(CatalogProduct.updated_at.desc())).all()
        mappings = db.scalars(select(ListingMapping).where(ListingMapping.workspace_id == workspace_id)).all()
    mapping_map = {(m.source, m.source_id, m.destination): m.destination_id for m in mappings}
    result = []
    for row in rows:
        try:
            product = json.loads(row.payload)
        except Exception:
            product = {"source": row.source, "source_id": row.source_id, "title": row.title, "variants": [], "images": []}
        variants = product.get("variants") or []
        product["variant_count"] = len(variants)
        product["stock_total"] = sum(max(0, int(v.get("quantity") or 0)) for v in variants)
        skus = [str(v.get("sku") or "").strip() for v in variants if str(v.get("sku") or "").strip()]
        product["sku_summary"] = ", ".join(list(dict.fromkeys(skus))[:3])
        product["mappings"] = {dest: mapping_map.get((row.source, row.source_id, dest), "") for dest in ("shopify", "etsy", "ebay")}
        result.append(product)
    return result


def save_mapping(workspace_id: str, source: str, source_id: str, destination: str, destination_id: str, payload: dict | None = None) -> None:
    with SessionLocal() as db:
        row = db.scalar(select(ListingMapping).where(ListingMapping.workspace_id == workspace_id, ListingMapping.source == source, ListingMapping.source_id == source_id, ListingMapping.destination == destination))
        if not row:
            row = ListingMapping(workspace_id=workspace_id, source=source, source_id=source_id, destination=destination)
            db.add(row)
        row.destination_id = destination_id
        row.payload = json.dumps(payload or {}, separators=(",", ":"))
        db.commit()


def create_job(workspace_id: str, kind: str) -> str:
    with SessionLocal() as db:
        job = SyncJob(workspace_id=workspace_id, kind=kind, status="queued", progress="0/0", message="Queued")
        db.add(job)
        db.commit()
        db.refresh(job)
        return job.id


def update_job(job_id: str, *, status: str | None = None, progress: str | None = None, message: str | None = None) -> None:
    with SessionLocal() as db:
        job = db.get(SyncJob, job_id)
        if not job:
            return
        if status is not None:
            job.status = status
        if progress is not None:
            job.progress = progress
        if message is not None:
            job.message = message[:2000]
        db.commit()


class ShopifyCloudClient:
    def __init__(self, shop_domain: str, access_token: str):
        domain = shop_domain.removeprefix("https://").rstrip("/")
        if not domain.endswith(".myshopify.com"):
            raise ValueError("Invalid Shopify store domain")
        self.domain = domain
        self.access_token = access_token
        self.endpoint = f"https://{domain}/admin/api/{SHOPIFY_API_VERSION}/graphql.json"

    async def graphql(self, query: str, variables: dict | None = None) -> dict:
        headers = {"X-Shopify-Access-Token": self.access_token, "Content-Type": "application/json"}
        async with httpx.AsyncClient(timeout=90) as client:
            response = await client.post(self.endpoint, headers=headers, json={"query": query, "variables": variables or {}})
            response.raise_for_status()
        payload = response.json()
        if payload.get("errors"):
            raise RuntimeError("; ".join(str(e.get("message") or e) for e in payload["errors"]))
        return payload["data"]

    async def test(self) -> dict:
        return (await self.graphql("{ shop { name myshopifyDomain } }"))["shop"]

    async def list_products(self) -> list[dict]:
        products: list[dict] = []
        cursor = None
        while True:
            data = await self.graphql(SHOPIFY_PRODUCTS_QUERY, {"cursor": cursor})
            connection = data["products"]
            for item in connection["nodes"]:
                images = []
                seen = set()
                for position, media in enumerate(item["media"]["nodes"], 1):
                    image = (media.get("preview") or {}).get("image") or {}
                    url = image.get("url")
                    if url and url not in seen:
                        seen.add(url)
                        images.append({"url": url, "position": position, "alt": image.get("altText") or item["title"], "variant_skus": []})
                variants = []
                for variant in item["variants"]["nodes"]:
                    variants.append({"source_id": str(variant.get("legacyResourceId") or variant["id"]), "sku": variant.get("sku") or f"shopify-{variant.get('legacyResourceId')}", "price": str(variant.get("price") or "0.00"), "quantity": int(variant.get("inventoryQuantity") or 0), "options": [{"name": o["name"], "value": o["value"]} for o in variant.get("selectedOptions", []) if o["name"] != "Title"], "barcode": variant.get("barcode") or None, "image_url": (variant.get("image") or {}).get("url")})
                products.append({"source": "shopify", "source_id": str(item["legacyResourceId"]), "title": item["title"], "description_html": item.get("descriptionHtml") or "", "status": str(item.get("status") or "").lower(), "currency": "", "vendor": item.get("vendor") or "", "product_type": item.get("productType") or "", "category_id": "", "category_name": "", "tags": item.get("tags") or [], "images": images, "variants": variants, "attributes": {}, "source_url": f"https://{self.domain}/admin/products/{item['legacyResourceId']}", "raw": item})
            if not connection["pageInfo"]["hasNextPage"]:
                return products
            cursor = connection["pageInfo"]["endCursor"]

    @staticmethod
    def _options(source_variants: list[dict]) -> tuple[list[dict], list[dict]]:
        option_names: list[str] = []
        for variant in source_variants:
            for option in variant.get("options") or []:
                name = str(option.get("name") or "").strip()
                if name and name not in option_names:
                    option_names.append(name)
        if source_variants and not option_names:
            option_names = ["Title"]
        normalised = []
        for variant in source_variants:
            supplied = {str(o.get("name") or "").strip(): str(o.get("value") or "").strip() for o in variant.get("options") or [] if str(o.get("name") or "").strip()}
            values = {name: supplied.get(name) or ("Default Title" if name == "Title" else "Default") for name in option_names}
            normalised.append((variant, values))
        product_options = []
        for position, name in enumerate(option_names, 1):
            values = list(dict.fromkeys(option_values[name] for _, option_values in normalised))
            product_options.append({"name": name, "position": position, "values": [{"name": value} for value in values]})
        variants = []
        for variant, option_values in normalised:
            record = {"sku": variant["sku"], "price": variant["price"], "optionValues": [{"optionName": name, "name": option_values[name]} for name in option_names], "inventoryItem": {"tracked": True}}
            if variant.get("barcode"):
                record["barcode"] = variant["barcode"]
            variants.append(record)
        return product_options, variants

    async def create_draft(self, product: dict) -> dict:
        product_options, variants = self._options(product.get("variants") or [])
        source_handle = f"shop-sync-{product['source']}-{product['source_id']}".lower()
        data = await self.graphql(PRODUCT_SET, {"synchronous": True, "identifier": {"handle": source_handle}, "input": {"handle": source_handle, "title": product["title"], "descriptionHtml": product.get("description_html") or "", "status": "DRAFT", "vendor": product.get("vendor") or "", "productType": product.get("product_type") or "", "tags": product.get("tags") or [], "productOptions": product_options, "variants": variants}})
        result = data["productSet"]
        if result["userErrors"]:
            raise RuntimeError("; ".join(e["message"] for e in result["userErrors"]))
        created = result["product"]
        if product.get("images"):
            media = [{"originalSource": i["url"], "mediaContentType": "IMAGE", "alt": i.get("alt") or product["title"]} for i in product["images"] if i.get("url")]
            if media:
                media_result = await self.graphql(PRODUCT_CREATE_MEDIA, {"productId": created["id"], "media": media})
                errors = media_result["productCreateMedia"]["mediaUserErrors"]
                if errors:
                    raise RuntimeError("Product created, but media failed: " + "; ".join(e["message"] for e in errors))
        await self._set_inventory(created["variants"]["nodes"], product.get("variants") or [])
        return created

    async def _set_inventory(self, created_variants: list[dict], source_variants: list[dict]) -> None:
        locations = (await self.graphql(LOCATION_QUERY))["locations"]["nodes"]
        if not locations:
            raise RuntimeError("Shopify store has no inventory location")
        location_id = locations[0]["id"]
        quantities_by_sku = {v["sku"]: max(0, int(v.get("quantity") or 0)) for v in source_variants}
        quantities = []
        for variant in created_variants:
            item_id = variant["inventoryItem"]["id"]
            await self.graphql(INVENTORY_ACTIVATE, {"inventoryItemId": item_id, "locationId": location_id, "idempotencyKey": str(uuid.uuid4())})
            current = await self.graphql(CURRENT_INVENTORY, {"inventoryItemId": item_id, "locationId": location_id})
            level = current["inventoryItem"]["inventoryLevel"]
            available = next((q["quantity"] for q in level["quantities"] if q["name"] == "available"), 0) if level else 0
            quantities.append({"inventoryItemId": item_id, "locationId": location_id, "quantity": quantities_by_sku.get(variant["sku"], 0), "changeFromQuantity": available})
        if quantities:
            result = await self.graphql(INVENTORY_SET, {"idempotencyKey": str(uuid.uuid4()), "input": {"name": "available", "reason": "correction", "quantities": quantities}})
            errors = result["inventorySetQuantities"]["userErrors"]
            if errors:
                raise RuntimeError("; ".join(e["message"] for e in errors))


class EtsyCloudClient:
    def __init__(self, broker: BrokerClient, credentials: dict):
        self.broker = broker
        self.credentials = credentials
        self.shop_id = str(credentials.get("shop_id") or "")
        if not self.shop_id:
            raise ValueError("Etsy shop ID is missing; reconnect Etsy")

    async def list_active_ids(self) -> list[str]:
        ids: list[str] = []
        offset = 0
        while True:
            payload = await self.broker.etsy_get(self.credentials, f"/v3/application/shops/{self.shop_id}/listings/active", {"limit": 100, "offset": offset})
            rows = payload.get("results") or []
            ids.extend(str(row["listing_id"]) for row in rows)
            offset += len(rows)
            if not rows or offset >= int(payload.get("count", offset)):
                return ids

    async def get_product(self, listing_id: str) -> dict:
        listing = await self.broker.etsy_get(self.credentials, f"/v3/application/listings/{listing_id}", {"includes": "Images"})
        listing["inventory"] = await self.broker.etsy_get(self.credentials, f"/v3/application/listings/{listing_id}/inventory")
        images = [{"url": image.get("url_fullxfull") or image.get("url_570xN") or image.get("url_170x135"), "position": int(image.get("rank", i + 1)), "alt": image.get("alt_text") or listing.get("title", ""), "variant_skus": []} for i, image in enumerate(listing.get("images", [])) if image.get("url_fullxfull") or image.get("url_570xN") or image.get("url_170x135")]
        variants = []
        for i, product in enumerate((listing.get("inventory") or {}).get("products") or []):
            offering = (product.get("offerings") or [{}])[0]
            price_data = offering.get("price") or listing.get("price") or {}
            amount = Decimal(str(price_data.get("amount", 0))) / Decimal(str(price_data.get("divisor", 100) or 100))
            sku = product.get("sku") or f"ETSY-{listing_id}-{i + 1}"
            options = []
            for value in product.get("property_values") or []:
                values = value.get("values") or []
                value_ids = value.get("value_ids") or []
                selected = values[0] if values else (value_ids[0] if value_ids else "")
                options.append({"name": str(value.get("property_name") or value.get("property_id")), "value": str(selected)})
            variants.append({"source_id": str(product.get("product_id") or sku), "sku": sku, "price": f"{amount:.2f}", "quantity": int(offering.get("quantity", 0)), "options": options, "barcode": None, "image_url": None})
        if not variants:
            price_data = listing.get("price") or {}
            amount = Decimal(str(price_data.get("amount", 0))) / Decimal(str(price_data.get("divisor", 100) or 100))
            sku = listing.get("sku", [f"ETSY-{listing_id}"])
            sku = sku[0] if isinstance(sku, list) and sku else str(sku)
            variants = [{"source_id": sku, "sku": sku, "price": f"{amount:.2f}", "quantity": int(listing.get("quantity", 0)), "options": [], "barcode": None, "image_url": None}]
        return {"source": "etsy", "source_id": str(listing_id), "title": listing.get("title", ""), "description_html": listing.get("description", ""), "status": listing.get("state", "active"), "currency": (listing.get("price") or {}).get("currency_code", "GBP"), "vendor": "", "product_type": str(listing.get("taxonomy_id", "")), "category_id": str(listing.get("taxonomy_id", "")), "category_name": "", "tags": list(listing.get("tags") or []), "images": images, "variants": variants, "attributes": {}, "source_url": listing.get("url") or f"https://www.etsy.com/listing/{listing_id}", "raw": listing}


def _text(node: ET.Element, path: str, default: str = "") -> str:
    found = node.find(path, NS)
    return found.text.strip() if found is not None and found.text else default


class EbayCloudClient:
    def __init__(self, access_token: str):
        self.access_token = access_token
        self.endpoint = "https://api.ebay.com/ws/api.dll"

    async def _call(self, name: str, body: str) -> ET.Element:
        headers = {"X-EBAY-API-CALL-NAME": name, "X-EBAY-API-COMPATIBILITY-LEVEL": "1423", "X-EBAY-API-SITEID": "3", "X-EBAY-API-IAF-TOKEN": self.access_token, "Content-Type": "text/xml"}
        async with httpx.AsyncClient(timeout=90) as client:
            response = await client.post(self.endpoint, content=body.encode(), headers=headers)
            response.raise_for_status()
        root = ET.fromstring(response.content)
        if _text(root, "e:Ack") not in {"Success", "Warning"}:
            raise RuntimeError(_text(root, ".//e:LongMessage", _text(root, ".//e:ShortMessage", "Unknown eBay error")))
        return root

    async def list_active_ids(self) -> list[str]:
        ids = []
        page = 1
        while True:
            body = f'''<?xml version="1.0" encoding="utf-8"?><GetMyeBaySellingRequest xmlns="urn:ebay:apis:eBLBaseComponents"><ActiveList><Include>true</Include><Pagination><EntriesPerPage>200</EntriesPerPage><PageNumber>{page}</PageNumber></Pagination></ActiveList><DetailLevel>ReturnSummary</DetailLevel></GetMyeBaySellingRequest>'''
            root = await self._call("GetMyeBaySelling", body)
            ids.extend(_text(item, "e:ItemID") for item in root.findall(".//e:ActiveList/e:ItemArray/e:Item", NS))
            total = int(_text(root, ".//e:ActiveList/e:PaginationResult/e:TotalNumberOfPages", "1"))
            if page >= total:
                return [item for item in ids if item]
            page += 1

    async def get_product(self, item_id: str) -> dict:
        body = f'''<?xml version="1.0" encoding="utf-8"?><GetItemRequest xmlns="urn:ebay:apis:eBLBaseComponents"><ItemID>{html_lib.escape(item_id)}</ItemID><DetailLevel>ReturnAll</DetailLevel><IncludeItemSpecifics>true</IncludeItemSpecifics></GetItemRequest>'''
        root = await self._call("GetItem", body)
        item = root.find("e:Item", NS)
        if item is None:
            raise RuntimeError(f"eBay returned no item for {item_id}")
        price_node = item.find("e:SellingStatus/e:CurrentPrice", NS) or item.find("e:StartPrice", NS)
        price = price_node.text if price_node is not None and price_node.text else "0.00"
        currency = price_node.attrib.get("currencyID", "GBP") if price_node is not None else "GBP"
        picture_urls = [_text(n, ".") for n in item.findall("e:PictureDetails/e:PictureURL", NS)]
        images = [{"url": url, "position": i + 1, "alt": _text(item, "e:Title"), "variant_skus": []} for i, url in enumerate(dict.fromkeys(picture_urls)) if url]
        variants = []
        for index, variation in enumerate(item.findall("e:Variations/e:Variation", NS)):
            options = [{"name": _text(c, "e:Name"), "value": _text(c, "e:Value")} for c in variation.findall("e:VariationSpecifics/e:NameValueList", NS)]
            sku = _text(variation, "e:SKU") or f"EBAY-{item_id}-{index + 1}"
            qty = max(0, int(_text(variation, "e:Quantity", "0")) - int(_text(variation, "e:SellingStatus/e:QuantitySold", "0")))
            variants.append({"source_id": sku, "sku": sku, "price": _text(variation, "e:StartPrice", price), "quantity": qty, "options": options, "barcode": None, "image_url": None})
        if not variants:
            available = _text(item, "e:QuantityAvailable", "")
            qty = max(0, int(available)) if available != "" else max(0, int(_text(item, "e:Quantity", "0")) - int(_text(item, "e:SellingStatus/e:QuantitySold", "0")))
            sku = _text(item, "e:SKU") or f"EBAY-{item_id}"
            variants = [{"source_id": sku, "sku": sku, "price": str(Decimal(price)), "quantity": qty, "options": [], "barcode": None, "image_url": None}]
        attributes = {}
        for spec in item.findall("e:ItemSpecifics/e:NameValueList", NS):
            name = _text(spec, "e:Name")
            values = [_text(v, ".") for v in spec.findall("e:Value", NS)]
            if name:
                attributes[name] = ", ".join(filter(None, values))
        return {"source": "ebay", "source_id": item_id, "title": _text(item, "e:Title"), "description_html": _text(item, "e:Description"), "status": "active", "currency": currency, "vendor": attributes.get("Brand", ""), "product_type": "", "category_id": _text(item, "e:PrimaryCategory/e:CategoryID"), "category_name": _text(item, "e:PrimaryCategory/e:CategoryName"), "tags": [], "images": images, "variants": variants, "attributes": attributes, "source_url": f"https://www.ebay.co.uk/itm/{item_id}", "raw": {}}
