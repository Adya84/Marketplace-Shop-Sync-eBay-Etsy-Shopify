from __future__ import annotations

import base64
import json
import time
from urllib.parse import parse_qs, urlparse

import httpx

from .etsy import EtsyClient


DEFAULT_BROKER_URL = "https://shop-sync-ebay-oauth.graffidoodle.workers.dev"


def parse_authorization_result(value: str) -> dict[str, str]:
    raw = value.strip()
    if not raw:
        raise ValueError("Paste the authorization result copied from the Etsy approval page")

    if "://" in raw:
        parsed = urlparse(raw)
        values = parse_qs(parsed.query, keep_blank_values=True)
        result = {key: entries[0] for key, entries in values.items() if entries}
        if result.get("error"):
            raise ValueError(result.get("error_description") or result["error"])
        if not result.get("code") or not result.get("state"):
            raise ValueError("The Etsy callback URL is missing its authorization code or state")
        result["authorization_result"] = raw
        return result

    payload_part = raw.split(".", 1)[0]
    try:
        padded = payload_part + "=" * (-len(payload_part) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded).decode())
    except Exception as exc:
        raise ValueError("Invalid Etsy authorization result; select Connect Etsy and try again") from exc

    if payload.get("error"):
        raise ValueError(payload.get("error_description") or payload["error"])
    if not payload.get("code") or not payload.get("state"):
        raise ValueError("The Etsy authorization result is missing its code or state")
    payload["authorization_result"] = raw
    return payload


class EtsyOAuthBroker:
    def __init__(self, base_url: str = DEFAULT_BROKER_URL, timeout: float = 30):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    async def start(self, state: str) -> str:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(f"{self.base_url}/api/etsy/oauth/start", json={"state": state})
            response.raise_for_status()
            payload = response.json()
        url = str(payload.get("authorization_url", ""))
        if not url.startswith("https://"):
            raise RuntimeError("Shop Sync Etsy sign-in service returned an invalid authorization URL")
        return url

    async def exchange(self, authorization_result: str) -> dict:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/api/etsy/oauth/exchange",
                json={"authorization_result": authorization_result},
            )
            response.raise_for_status()
            return response.json()

    async def refresh(self, credentials: dict) -> dict:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/api/etsy/oauth/refresh",
                json={
                    "refresh_token": credentials["refresh_token"],
                    "refresh_key": credentials["refresh_key"],
                },
            )
            response.raise_for_status()
            payload = response.json()
        updated = dict(credentials)
        updated["access_token"] = payload["access_token"]
        updated["expires_at"] = time.time() + int(payload.get("expires_in", 3600))
        updated["refresh_token"] = payload.get("refresh_token") or updated["refresh_token"]
        updated["refresh_key"] = payload.get("refresh_key") or updated["refresh_key"]
        updated["broker_key"] = payload["broker_key"]
        return updated

    async def get(self, access_token: str, broker_key: str, path: str, params=None) -> dict:
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                f"{self.base_url}/api/etsy/api/get",
                json={
                    "access_token": access_token,
                    "broker_key": broker_key,
                    "path": path,
                    "params": params or {},
                },
            )
            response.raise_for_status()
            return response.json()


class BrokerEtsyClient(EtsyClient):
    """Etsy client that keeps the publisher API secret on the hosted broker."""

    def __init__(
        self,
        shop_id: str,
        access_token: str,
        refresh_token: str = "",
        expires_at: float = 0,
        broker_key: str = "",
        refresh_key: str = "",
        broker_url: str = DEFAULT_BROKER_URL,
        oauth_mode: str = "publisher_broker",
    ):
        self.keystring = ""
        self.shared_secret = ""
        self.shop_id = str(shop_id).strip()
        self.access_token = access_token.strip()
        self.refresh_token = refresh_token.strip()
        self.expires_at = float(expires_at or 0)
        self.broker_key = broker_key.strip()
        self.refresh_key = refresh_key.strip()
        self.broker_url = broker_url.rstrip("/")
        self.oauth_mode = oauth_mode
        self.broker = EtsyOAuthBroker(self.broker_url)
        if not self.shop_id or not self.access_token or not self.broker_key:
            raise ValueError("Etsy broker credentials are incomplete")

    async def _refresh(self):
        if not self.refresh_token or not self.refresh_key:
            return
        updated = await self.broker.refresh(self.credential_payload())
        self.access_token = updated["access_token"]
        self.refresh_token = updated["refresh_token"]
        self.refresh_key = updated["refresh_key"]
        self.broker_key = updated["broker_key"]
        self.expires_at = float(updated["expires_at"])

    async def _get(self, path: str, params=None):
        if self.refresh_token and (not self.expires_at or time.time() >= self.expires_at - 300):
            await self._refresh()
        try:
            return await self.broker.get(self.access_token, self.broker_key, path, params)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 401 and self.refresh_token and self.refresh_key:
                await self._refresh()
                return await self.broker.get(self.access_token, self.broker_key, path, params)
            raise

    def credential_payload(self) -> dict:
        return {
            "shop_id": self.shop_id,
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "expires_at": self.expires_at,
            "broker_key": self.broker_key,
            "refresh_key": self.refresh_key,
            "broker_url": self.broker_url,
            "oauth_mode": "publisher_broker",
        }
