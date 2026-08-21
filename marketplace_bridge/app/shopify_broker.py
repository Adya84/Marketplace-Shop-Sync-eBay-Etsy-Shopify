from __future__ import annotations

import base64
import json
from urllib.parse import parse_qs, urlparse

import httpx


DEFAULT_BROKER_URL = "https://shop-sync-ebay-oauth.graffidoodle.workers.dev"


def parse_authorization_result(value: str) -> dict[str, str]:
    raw = value.strip()
    if not raw:
        raise ValueError("Paste the authorization result copied from the Shopify approval page")

    if "://" in raw:
        parsed = urlparse(raw)
        values = parse_qs(parsed.query, keep_blank_values=True)
        result = {key: entries[0] for key, entries in values.items() if entries}
        if result.get("error"):
            raise ValueError(result.get("error_description") or result["error"])
        if not result.get("code") or not result.get("state"):
            raise ValueError("The Shopify callback URL is missing its authorization code or state")
        result["authorization_result"] = raw
        return result

    payload_part = raw.split(".", 1)[0]
    try:
        padded = payload_part + "=" * (-len(payload_part) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded).decode())
    except Exception as exc:
        raise ValueError("Invalid Shopify authorization result; select Connect Shopify and try again") from exc

    if payload.get("error"):
        raise ValueError(payload.get("error_description") or payload["error"])
    if not payload.get("code") or not payload.get("state") or not payload.get("shop"):
        raise ValueError("The Shopify authorization result is missing its code, state or shop")
    payload["authorization_result"] = raw
    return payload


class ShopifyOAuthBroker:
    def __init__(self, base_url: str = DEFAULT_BROKER_URL, timeout: float = 30):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    async def start(self, shop: str, state: str) -> str:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/api/shopify/oauth/start",
                json={"shop": shop, "state": state},
            )
            response.raise_for_status()
            payload = response.json()
        url = str(payload.get("authorization_url", ""))
        if not url.startswith("https://") or ".myshopify.com/admin/oauth/authorize" not in url:
            raise RuntimeError("Shop Sync Shopify sign-in service returned an invalid authorization URL")
        return url

    async def exchange(self, authorization_result: str) -> dict:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/api/shopify/oauth/exchange",
                json={"authorization_result": authorization_result},
            )
            response.raise_for_status()
            return response.json()
