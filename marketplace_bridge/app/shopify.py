from __future__ import annotations

import asyncio
import time

import httpx


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
mutation Activate($inventoryItemId: ID!, $locationId: ID!) {
  inventoryActivate(inventoryItemId: $inventoryItemId, locationId: $locationId) {
    inventoryLevel { id } userErrors { field message }
  }
}
"""

INVENTORY_SET = """
mutation SetInventory($input: InventorySetQuantitiesInput!) {
  inventorySetQuantities(input: $input) {
    inventoryAdjustmentGroup { createdAt }
    userErrors { field message code }
  }
}
"""

LOCATION_QUERY = "{ locations(first: 1) { nodes { id name } } }"


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
            await self.graphql(INVENTORY_ACTIVATE, {"inventoryItemId": inventory_item_id, "locationId": location_id})
            quantities.append({"inventoryItemId": inventory_item_id, "locationId": location_id, "quantity": quantities_by_sku.get(variant["sku"], 0)})
        if quantities:
            data = await self.graphql(INVENTORY_SET, {"input": {"name": "on_hand", "reason": "correction", "ignoreCompareQuantity": True, "quantities": quantities}})
            errors = data["inventorySetQuantities"]["userErrors"]
            if errors:
                raise RuntimeError("; ".join(e["message"] for e in errors))
