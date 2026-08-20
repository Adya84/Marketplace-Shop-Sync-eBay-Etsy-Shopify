from __future__ import annotations

import hashlib
import hmac
import json
import time
from html import escape
from typing import Any

import httpx

from .models import Image, OptionValue, Product, Variant


class TikTokShopClient:
    """Small TikTok Shop Open API client for importing a seller catalogue."""

    base_url = "https://open-api.tiktokglobalshop.com"

    def __init__(self, app_key: str, app_secret: str, access_token: str, shop_cipher: str):
        self.app_key = app_key.strip()
        self.app_secret = app_secret.strip()
        self.access_token = access_token.strip()
        self.shop_cipher = shop_cipher.strip()

    def generate_sign(self, path: str, params: dict[str, Any], body: str = "") -> str:
        filtered = {key: value for key, value in params.items() if key not in {"sign", "access_token"}}
        parameter_text = "".join(f"{key}{filtered[key]}" for key in sorted(filtered))
        wrapped = f"{self.app_secret}{path}{parameter_text}{body}{self.app_secret}"
        return hmac.new(self.app_secret.encode(), wrapped.encode(), hashlib.sha256).hexdigest()

    async def _request(self, method: str, path: str, *, query: dict[str, Any] | None = None,
                       body: dict[str, Any] | None = None, include_shop: bool = True) -> dict[str, Any]:
        params: dict[str, Any] = {"app_key": self.app_key, "timestamp": int(time.time())}
        if include_shop:
            params["shop_cipher"] = self.shop_cipher
        params.update(query or {})
        body_text = json.dumps(body, separators=(",", ":"), ensure_ascii=False) if body is not None else ""
        params["sign"] = self.generate_sign(path, params, body_text)
        headers = {"content-type": "application/json", "x-tts-access-token": self.access_token}
        async with httpx.AsyncClient(timeout=45) as client:
            response = await client.request(method, f"{self.base_url}{path}", params=params,
                                            headers=headers, content=body_text or None)
            response.raise_for_status()
            payload = response.json()
        if payload.get("code") not in (None, 0, "0"):
            raise RuntimeError(payload.get("message") or f"TikTok Shop error {payload.get('code')}")
        return payload.get("data") or {}

    async def test(self) -> dict[str, Any]:
        data = await self._request("GET", "/authorization/202309/shops", include_shop=False)
        shops = data.get("shops") or []
        match = next((shop for shop in shops if shop.get("cipher") == self.shop_cipher), None)
        if not match:
            raise ValueError("Shop cipher was not found in the shops authorised for this token")
        return match

    async def list_active_ids(self) -> list[str]:
        ids: list[str] = []
        page_token = ""
        while True:
            query: dict[str, Any] = {"page_size": 100}
            if page_token:
                query["page_token"] = page_token
            data = await self._request("POST", "/product/202309/products/search", query=query,
                                       body={"status": "ACTIVATE"})
            products = data.get("products") or []
            ids.extend(str(item["id"]) for item in products if item.get("id"))
            page_token = str(data.get("next_page_token") or "")
            if not page_token or not products:
                return list(dict.fromkeys(ids))

    async def get_product(self, product_id: str) -> Product:
        data = await self._request("GET", f"/product/202309/products/{product_id}")
        return self.normalise(data)

    @staticmethod
    def _image_url(value: Any) -> str:
        if isinstance(value, str):
            return value
        if not isinstance(value, dict):
            return ""
        urls = value.get("urls") or value.get("url_list") or []
        return str((urls[0] if urls else value.get("url")) or "")

    @classmethod
    def normalise(cls, item: dict[str, Any]) -> Product:
        title = str(item.get("title") or "Untitled TikTok product")
        source_id = str(item.get("id") or item.get("product_id") or "")
        image_values = item.get("main_images") or item.get("images") or []
        images = [Image(url=url, position=index, alt=title)
                  for index, value in enumerate(image_values, 1)
                  if (url := cls._image_url(value))]

        variants: list[Variant] = []
        for sku in item.get("skus") or []:
            price_data = sku.get("price") or sku.get("sales_price") or {}
            price = str(price_data.get("tax_exclusive_price") or price_data.get("tax_inclusive_price")
                        or price_data.get("amount") or sku.get("price") or "0.00")
            inventory = sku.get("inventory") or []
            quantity = (sum(int(entry.get("quantity") or 0) for entry in inventory)
                        if isinstance(inventory, list) else int(inventory or 0))
            options: list[OptionValue] = []
            variant_image = ""
            for attribute in sku.get("sales_attributes") or []:
                name = str(attribute.get("name") or attribute.get("attribute_name") or "Option")
                value = str(attribute.get("value_name") or attribute.get("value") or "Default")
                options.append(OptionValue(name=name, value=value))
                variant_image = variant_image or cls._image_url(attribute.get("sku_img") or attribute.get("image"))
            variants.append(Variant(
                source_id=str(sku.get("id") or sku.get("sku_id") or source_id),
                sku=str(sku.get("seller_sku") or sku.get("sku") or ""), price=price,
                quantity=quantity, options=options,
                barcode=str(sku.get("gtin") or sku.get("barcode") or "") or None,
                image_url=variant_image or None,
            ))

        category_chains = item.get("category_chains") or []
        category = category_chains[-1] if category_chains else item.get("category") or {}
        description = str(item.get("description") or "")
        if description and "<" not in description:
            description = "<p>" + escape(description).replace("\n", "<br>") + "</p>"
        currency = ""
        if variants:
            first_sku = (item.get("skus") or [{}])[0]
            first_price = first_sku.get("price") or first_sku.get("sales_price") or {}
            if isinstance(first_price, dict):
                currency = str(first_price.get("currency") or first_price.get("currency_code") or "")
        return Product(
            source="tiktok", source_id=source_id, title=title, description_html=description,
            status=str(item.get("status") or "active").lower(), currency=currency or "GBP",
            vendor=str(item.get("brand", {}).get("name") if isinstance(item.get("brand"), dict)
                       else item.get("brand") or ""),
            product_type=str(category.get("local_name") or category.get("name") or ""),
            category_id=str(category.get("id") or ""),
            category_name=str(category.get("local_name") or category.get("name") or ""),
            images=images, variants=variants, source_url=str(item.get("product_url") or ""), raw=item,
        )

