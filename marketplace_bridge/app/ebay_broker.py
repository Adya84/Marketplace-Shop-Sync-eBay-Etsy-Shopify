from __future__ import annotations

import base64
import json
import time
from urllib.parse import parse_qs, urlparse

import httpx


DEFAULT_BROKER_URL = "https://shop-sync-ebay-compliance.zesty-flame-5295.chatgpt.site"


def parse_authorization_result(value: str) -> dict[str, str]:
    """Accept the Shop Sync callback result or a full callback URL.

    The hosted callback copies a signed, opaque result in the form
    ``payload.signature``. Older/manual flows that provide a full callback URL
    are still accepted so existing test setups remain usable.
    """
    raw = value.strip()
    if not raw:
        raise ValueError("Paste the authorization result copied from the eBay approval page")

    if "://" in raw:
        parsed = urlparse(raw)
        values = parse_qs(parsed.query, keep_blank_values=True)
        result = {key: entries[0] for key, entries in values.items() if entries}
        if result.get("error"):
            raise ValueError(result.get("error_description") or result["error"])
        if not result.get("code") or not result.get("state"):
            raise ValueError("The eBay callback URL is missing its authorization code or state")
        result["authorization_result"] = raw
        return result

    payload_part = raw.split(".", 1)[0]
    try:
        padded = payload_part + "=" * (-len(payload_part) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded).decode())
    except Exception as exc:
        raise ValueError("Invalid eBay authorization result; select Connect eBay and try again") from exc

    if payload.get("error"):
        raise ValueError(payload.get("error_description") or payload["error"])
    if not payload.get("code") or not payload.get("state"):
        raise ValueError("The eBay authorization result is missing its code or state")
    payload["authorization_result"] = raw
    return payload


class EbayOAuthBroker:
    def __init__(self, base_url: str = DEFAULT_BROKER_URL, timeout: float = 30):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    async def start(self, state: str, environment: str = "production") -> str:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/api/ebay/oauth/start",
                json={"state": state, "environment": environment},
            )
            response.raise_for_status()
            payload = response.json()
        url = str(payload.get("authorization_url", ""))
        if not url.startswith("https://"):
            raise RuntimeError("Shop Sync eBay sign-in service returned an invalid authorization URL")
        return url

    async def exchange(self, authorization_result: str, environment: str = "production") -> dict:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/api/ebay/oauth/exchange",
                json={"authorization_result": authorization_result, "environment": environment},
            )
            response.raise_for_status()
            return response.json()

    async def refresh(self, credentials: dict, environment: str = "production") -> dict:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/api/ebay/oauth/refresh",
                json={
                    "refresh_token": credentials["refresh_token"],
                    "refresh_key": credentials["refresh_key"],
                    "scopes": credentials.get("scopes", []),
                    "environment": environment,
                },
            )
            response.raise_for_status()
            payload = response.json()
        updated = dict(credentials)
        updated["access_token"] = payload["access_token"]
        updated["expires_at"] = time.time() + int(payload.get("expires_in", 7200))
        if payload.get("refresh_token"):
            updated["refresh_token"] = payload["refresh_token"]
        if payload.get("refresh_key"):
            updated["refresh_key"] = payload["refresh_key"]
        return updated

    async def ensure_access_token(self, credentials: dict, environment: str = "production") -> dict:
        expires_at = float(credentials.get("expires_at", 0) or 0)
        if credentials.get("refresh_token") and credentials.get("refresh_key") and (
            not credentials.get("access_token") or expires_at <= time.time() + 120
        ):
            return await self.refresh(credentials, environment)
        return credentials
