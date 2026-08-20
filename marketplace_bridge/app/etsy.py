from __future__ import annotations

import time
from decimal import Decimal

import httpx

from .models import Image, OptionValue, Product, Variant


class EtsyClient:
    """Reads a seller's complete Etsy inventory through Open API v3."""

    def __init__(
        self,
        keystring: str,
        shared_secret: str,
        shop_id: str,
        access_token: str,
        refresh_token: str = "",
        expires_at: float = 0,
    ):
        self.keystring = keystring.strip()
        self.shared_secret = shared_secret.strip()
        self.shop_id = str(shop_id).strip()
        self.access_token = access_token.strip()
        self.refresh_token = refresh_token.strip()
        self.expires_at = float(expires_at or 0)
        if not all((self.keystring, self.shared_secret, self.shop_id, self.access_token)):
            raise ValueError("Etsy API key, shared secret, shop ID and access token are required")

    @property
    def api_key(self) -> str:
        return f"{self.keystring}:{self.shared_secret}"

    async def _refresh(self):
        if not self.refresh_token:
            return
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                "https://api.etsy.com/v3/public/oauth/token",
                data={
                    "grant_type": "refresh_token",
                    "client_id": self.keystring,
                    "refresh_token": self.refresh_token,
                },
            )
            response.raise_for_status()
        payload = response.json()
        self.access_token = payload["access_token"]
        self.refresh_token = payload.get("refresh_token", self.refresh_token)
        self.expires_at = time.time() + int(payload.get("expires_in", 3600))

    async def _get(self, path: str, params=None):
        if self.refresh_token and (not self.expires_at or time.time() >= self.expires_at - 300):
            await self._refresh()
        headers = {"x-api-key": self.api_key, "Authorization": f"Bearer {self.access_token}"}
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.get(f"https://api.etsy.com{path}", params=params, headers=headers)
            if response.status_code == 401 and self.refresh_token:
                await self._refresh()
                headers["Authorization"] = f"Bearer {self.access_token}"
                response = await client.get(f"https://api.etsy.com{path}", params=params, headers=headers)
            response.raise_for_status()
        return response.json()

    def credential_payload(self) -> dict:
        return {
            "keystring": self.keystring,
            "shared_secret": self.shared_secret,
            "shop_id": self.shop_id,
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "expires_at": self.expires_at,
        }

    async def test(self):
        return await self._get(f"/v3/application/shops/{self.shop_id}")

    async def list_active_ids(self) -> list[str]:
        ids = []
        offset = 0
        while True:
            payload = await self._get(
                f"/v3/application/shops/{self.shop_id}/listings/active",
                {"limit": 100, "offset": offset},
            )
            rows = payload.get("results", [])
            ids.extend(str(row["listing_id"]) for row in rows)
            offset += len(rows)
            if not rows or offset >= int(payload.get("count", offset)):
                return ids

    async def get_product(self, listing_id: str) -> Product:
        listing = await self._get(
            f"/v3/application/listings/{listing_id}",
            {"includes": "Images,Inventory"},
        )
        return self._normalise(listing)

    def _normalise(self, listing: dict) -> Product:
        listing_id = str(listing["listing_id"])
        images = [
            Image(
                url=image.get("url_fullxfull") or image.get("url_570xN") or image.get("url_170x135"),
                position=int(image.get("rank", index + 1)),
                alt=image.get("alt_text") or listing.get("title", ""),
            )
            for index, image in enumerate(listing.get("images", []))
            if image.get("url_fullxfull") or image.get("url_570xN") or image.get("url_170x135")
        ]
        inventory = listing.get("inventory") or {}
        products = inventory.get("products") or []
        variants = []
        for index, product in enumerate(products):
            offerings = product.get("offerings") or [{}]
            offering = offerings[0]
            price_data = offering.get("price") or listing.get("price") or {}
            divisor = Decimal(str(price_data.get("divisor", 100) or 100))
            amount = Decimal(str(price_data.get("amount", 0))) / divisor
            sku = product.get("sku") or f"ETSY-{listing_id}-{index + 1}"
            options = []
            for value in product.get("property_values", []):
                values = value.get("values") or []
                value_ids = value.get("value_ids") or []
                selected = values[0] if values else (value_ids[0] if value_ids else "")
                options.append(OptionValue(
                    str(value.get("property_name") or value.get("property_id")),
                    str(selected),
                ))
            variants.append(Variant(
                source_id=str(product.get("product_id") or sku),
                sku=sku,
                price=f"{amount:.2f}",
                quantity=int(offering.get("quantity", 0)),
                options=options,
            ))
        if not variants:
            price_data = listing.get("price") or {}
            amount = Decimal(str(price_data.get("amount", 0))) / Decimal(str(price_data.get("divisor", 100) or 100))
            sku = listing.get("sku", [f"ETSY-{listing_id}"])
            sku = sku[0] if isinstance(sku, list) and sku else str(sku)
            variants = [Variant(source_id=sku, sku=sku, price=f"{amount:.2f}", quantity=int(listing.get("quantity", 0)))]
        attributes = {
            str(prop.get("property_name") or prop.get("property_id")): ", ".join(map(str, prop.get("values", [])))
            for prop in listing.get("attributes", [])
        }
        return Product(
            source="etsy",
            source_id=listing_id,
            title=listing.get("title", ""),
            description_html=listing.get("description", ""),
            status=listing.get("state", "active"),
            currency=(listing.get("price") or {}).get("currency_code", "GBP"),
            vendor=attributes.get("Who made it?", ""),
            product_type=str(listing.get("taxonomy_id", "")),
            tags=list(listing.get("tags", [])),
            images=images,
            variants=variants,
            attributes=attributes,
            source_url=listing.get("url") or f"https://www.etsy.com/listing/{listing_id}",
        )

