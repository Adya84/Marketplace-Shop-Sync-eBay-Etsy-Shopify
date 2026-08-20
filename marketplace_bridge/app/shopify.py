from __future__ import annotations

import asyncio
import time
import uuid

import httpx

from .models import Image, OptionValue, Product, Variant


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

VARIANT_APPEND_MEDIA = """
mutation AppendVariantMedia($productId: ID!, $variantMedia: [ProductVariantAppendMediaInput!]!) {
  productVariantAppendMedia(productId: $productId, variantMedia: $variantMedia) {
    productVariants { id sku }
    userErrors { field message code }
  }
}
"""

INVENTORY_ACTIVATE = """
mutation Activate($inventoryItemId: ID!, $locationId: ID!, $idempotencyKey: String!) {
  inventoryActivate(inventoryItemId: $inventoryItemId, locationId: $locationId)
    @idempotent(key: $idempotencyKey) {
    inventoryLevel { id quantities(names: ["available"]) { name quantity } }
    userErrors { field message }
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

CURRENT_INVENTORY = """
query CurrentInventory($inventoryItemId: ID!, $locationId: ID!) {
  inventoryItem(id: $inventoryItemId) {
    inventoryLevel(locationId: $locationId) {
      quantities(names: ["available"]) { name quantity }
    }
  }
}
"""

LOCATION_QUERY = "{ locations(first: 1) { nodes { id name } } }"

PRODUCTS_QUERY = """
query ShopSyncProducts($cursor: String) {
  products(first: 50, after: $cursor) {
    pageInfo { hasNextPage endCursor }
    nodes {
      id legacyResourceId title descriptionHtml status vendor productType tags handle
      featuredMedia { preview { image { url altText } } }
      media(first: 100) { nodes { preview { image { url altText } } } }
      variants(first: 250) {
        nodes { id legacyResourceId title sku barcode price inventoryQuantity selectedOptions { name value }
          image { url altText }
        }
      }
    }
  }
}
"""


class ShopifyClient:
    def __init__(
        self,
        shop_domain: str,
        api_version: str,
        *,
        client_id: str | None = None,
        client_secret: str | None = None,
        access_token: str | None = None,
    ):
        domain = shop_domain.removeprefix("https://").rstrip("/")
        if not domain.endswith(".myshopify.com"):
            raise ValueError("Use the permanent store domain ending in .myshopify.com")
        if not access_token and not (client_id and client_secret):
            raise ValueError("Shopify client credentials are required")
        self.domain = domain
        self.endpoint = f"https://{domain}/admin/api/{api_version}/graphql.json"
        self.token_endpoint = f"https://{domain}/admin/oauth/access_token"
        self.client_id = client_id
        self.client_secret = client_secret
        self._access_token = access_token
        self._expires_at = float("inf") if access_token else 0.0
        self._token_lock = asyncio.Lock()

    async def _token(self) -> str:
        # Renew five minutes early so a long-running import cannot cross expiry.
        if self._access_token and time.time() < self._expires_at - 300:
            return self._access_token
        async with self._token_lock:
            if self._access_token and time.time() < self._expires_at - 300:
                return self._access_token
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(
                    self.token_endpoint,
                    data={
                        "grant_type": "client_credentials",
                        "client_id": self.client_id,
                        "client_secret": self.client_secret,
                    },
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
                response.raise_for_status()
            payload = response.json()
            token = payload.get("access_token")
            if not token:
                raise RuntimeError("Shopify did not return an access token")
            self._access_token = token
            self._expires_at = time.time() + int(payload.get("expires_in", 3600))
            return token

    async def graphql(self, query: str, variables=None):
        token = await self._token()
        headers = {"X-Shopify-Access-Token": token, "Content-Type": "application/json"}
        async with httpx.AsyncClient(timeout=90) as client:
            response = await client.post(self.endpoint, headers=headers, json={"query": query, "variables": variables or {}})
            response.raise_for_status()
        payload = response.json()
        if payload.get("errors"):
            raise RuntimeError("; ".join(error["message"] for error in payload["errors"]))
        return payload["data"]

    async def test(self):
        data = await self.graphql("{ shop { name myshopifyDomain } }")
        return data["shop"]

    async def list_products(self) -> list[Product]:
        products = []
        cursor = None
        while True:
            data = await self.graphql(PRODUCTS_QUERY, {"cursor": cursor})
            connection = data["products"]
            for item in connection["nodes"]:
                images = []
                seen = set()
                for position, media in enumerate(item["media"]["nodes"], 1):
                    image = (media.get("preview") or {}).get("image") or {}
                    url = image.get("url")
                    if url and url not in seen:
                        seen.add(url)
                        images.append(Image(url=url, position=position, alt=image.get("altText") or item["title"]))
                variants = []
                for variant in item["variants"]["nodes"]:
                    variants.append(Variant(
                        source_id=str(variant.get("legacyResourceId") or variant["id"]),
                        sku=variant.get("sku") or f"shopify-{variant.get('legacyResourceId')}",
                        price=str(variant.get("price") or "0.00"),
                        quantity=int(variant.get("inventoryQuantity") or 0),
                        options=[OptionValue(name=o["name"], value=o["value"]) for o in variant.get("selectedOptions", []) if o["name"] != "Title"],
                        barcode=variant.get("barcode") or None,
                        image_url=(variant.get("image") or {}).get("url"),
                    ))
                products.append(Product(
                    source="shopify", source_id=str(item["legacyResourceId"]), title=item["title"],
                    description_html=item.get("descriptionHtml") or "", status=str(item.get("status") or "").lower(),
                    currency="", vendor=item.get("vendor") or "", product_type=item.get("productType") or "",
                    tags=item.get("tags") or [], images=images, variants=variants,
                    source_url=f"https://{self.domain}/admin/products/{item['legacyResourceId']}", raw=item,
                ))
            if not connection["pageInfo"]["hasNextPage"]:
                return products
            cursor = connection["pageInfo"]["endCursor"]

    async def create_draft(self, product: dict):
        option_names = []
        for variant in product["variants"]:
            for option in variant["options"]:
                if option["name"] not in option_names:
                    option_names.append(option["name"])
        product_options = []
        for position, name in enumerate(option_names, 1):
            values = []
            for variant in product["variants"]:
                values.extend(o["value"] for o in variant["options"] if o["name"] == name)
            product_options.append({"name": name, "position": position, "values": [{"name": value} for value in dict.fromkeys(values)]})

        variants = []
        for variant in product["variants"]:
            record = {
                "sku": variant["sku"], "price": variant["price"],
                "optionValues": [{"optionName": o["name"], "name": o["value"]} for o in variant["options"]],
                "inventoryItem": {"tracked": True},
            }
            if variant.get("barcode"):
                record["barcode"] = variant["barcode"]
            variants.append(record)
        # A deterministic handle makes retries idempotent without requiring a
        # merchant-specific unique metafield definition.
        source_handle = f"shop-sync-{product['source']}-{product['source_id']}".lower()
        product_input = {
            "handle": source_handle,
            "title": product["title"], "descriptionHtml": product["description_html"], "status": "DRAFT",
            "vendor": product.get("vendor") or "", "productType": product.get("product_type") or "",
            "tags": product.get("tags", []), "productOptions": product_options, "variants": variants,
        }
        data = await self.graphql(PRODUCT_SET, {
            "synchronous": True,
            "identifier": {"handle": source_handle},
            "input": product_input,
        })
        result = data["productSet"]
        if result["userErrors"]:
            raise RuntimeError("; ".join(error["message"] for error in result["userErrors"]))
        created = result["product"]
        if product.get("images"):
            media = [{"originalSource": image["url"], "mediaContentType": "IMAGE", "alt": image.get("alt") or product["title"]} for image in product["images"]]
            media_result = await self.graphql(PRODUCT_CREATE_MEDIA, {"productId": created["id"], "media": media})
            media_payload = media_result["productCreateMedia"]
            errors = media_payload["mediaUserErrors"]
            if errors:
                raise RuntimeError("Product created, but media failed: " + "; ".join(e["message"] for e in errors))
            # The response retains input order, allowing source variation images
            # to be associated with the correct Shopify variants.
            media_ids_by_url = {
                image["url"]: uploaded["id"]
                for image, uploaded in zip(product["images"], media_payload["media"])
                if uploaded and uploaded.get("id")
            }
            variants_by_sku = {variant["sku"]: variant["id"] for variant in created["variants"]["nodes"]}
            variant_media = []
            for image in product["images"]:
                media_id = media_ids_by_url.get(image["url"])
                for sku in image.get("variant_skus", []):
                    if media_id and sku in variants_by_sku:
                        variant_media.append({"variantId": variants_by_sku[sku], "mediaIds": [media_id]})
            if variant_media:
                linked = await self.graphql(VARIANT_APPEND_MEDIA, {"productId": created["id"], "variantMedia": variant_media})
                link_errors = linked["productVariantAppendMedia"]["userErrors"]
                if link_errors:
                    raise RuntimeError("Product created, but variant media linking failed: " + "; ".join(e["message"] for e in link_errors))
        await self._set_inventory(created["variants"]["nodes"], product["variants"])
        return created

    async def _set_inventory(self, created_variants: list[dict], source_variants: list[dict]):
        location_data = await self.graphql(LOCATION_QUERY)
        locations = location_data["locations"]["nodes"]
        if not locations:
            raise RuntimeError("Shopify store has no inventory location")
        location_id = locations[0]["id"]
        quantities = []
        quantities_by_sku = {v["sku"]: v["quantity"] for v in source_variants}
        for variant in created_variants:
            inventory_item_id = variant["inventoryItem"]["id"]
            await self.graphql(INVENTORY_ACTIVATE, {
                "inventoryItemId": inventory_item_id,
                "locationId": location_id,
                "idempotencyKey": str(uuid.uuid4()),
            })
            current_data = await self.graphql(CURRENT_INVENTORY, {
                "inventoryItemId": inventory_item_id,
                "locationId": location_id,
            })
            level = current_data["inventoryItem"]["inventoryLevel"]
            if not level:
                raise RuntimeError("Shopify inventory level was not activated")
            current_available = next(
                (quantity["quantity"] for quantity in level["quantities"] if quantity["name"] == "available"),
                0,
            )
            quantities.append({
                "inventoryItemId": inventory_item_id,
                "locationId": location_id,
                "quantity": quantities_by_sku.get(variant["sku"], 0),
                "changeFromQuantity": current_available,
            })
        if quantities:
            data = await self.graphql(INVENTORY_SET, {
                "idempotencyKey": str(uuid.uuid4()),
                "input": {"name": "available", "reason": "correction", "quantities": quantities},
            })
            errors = data["inventorySetQuantities"]["userErrors"]
            if errors:
                raise RuntimeError("; ".join(e["message"] for e in errors))
