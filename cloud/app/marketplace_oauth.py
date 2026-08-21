from __future__ import annotations

import base64
import json
import time
from urllib.parse import parse_qs, urlparse

import httpx


def decode_result(value: str) -> dict:
    raw = str(value or "").strip()
    if not raw:
        raise ValueError("Paste the authorization result from the marketplace approval page.")
    if "://" in raw:
        parsed = urlparse(raw)
        values = parse_qs(parsed.query, keep_blank_values=True)
        payload = {key: entries[0] for key, entries in values.items() if entries}
        if payload.get("error"):
            raise ValueError(payload.get("error_description") or payload["error"])
        payload["authorization_result"] = raw
        return payload
    payload_part = raw.split(".", 1)[0]
    try:
        padded = payload_part + "=" * (-len(payload_part) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded).decode())
    except Exception as exc:
        raise ValueError("Invalid authorization result. Start the connection again.") from exc
    if payload.get("error"):
        raise ValueError(payload.get("error_description") or payload["error"])
    payload["authorization_result"] = raw
    return payload


class BrokerClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    async def _post(self, path: str, payload: dict, timeout: float = 45) -> dict:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(f"{self.base_url}{path}", json=payload)
            if response.status_code >= 400:
                detail = ""
                try:
                    body = response.json()
                    detail = str(body.get("detail") or body.get("error") or "")
                except Exception:
                    detail = response.text[:500]
                raise RuntimeError(detail or f"Shop Sync connection service returned HTTP {response.status_code}")
            if not response.content:
                return {}
            return response.json()

    async def start(self, provider: str, state: str, *, shop: str = "") -> str:
        if provider == "shopify":
            payload = {"state": state, "shop": shop}
        elif provider == "ebay":
            payload = {"state": state, "environment": "production"}
        else:
            payload = {"state": state}
        data = await self._post(f"/api/{provider}/oauth/start", payload)
        url = str(data.get("authorization_url") or "")
        if not url.startswith("https://"):
            raise RuntimeError(f"{provider.title()} sign-in service returned an invalid authorization URL")
        return url

    async def exchange(self, provider: str, authorization_result: str, *, shop: str = "") -> dict:
        payload: dict = {"authorization_result": authorization_result}
        if provider == "ebay":
            payload["environment"] = "production"
        if provider == "shopify" and shop:
            payload["shop"] = shop
        data = await self._post(f"/api/{provider}/oauth/exchange", payload)
        result = dict(data)
        expires_in = int(result.get("expires_in") or (7200 if provider == "ebay" else 3600))
        result["expires_at"] = time.time() + expires_in
        result["oauth_mode"] = "publisher_broker"
        result["broker_url"] = self.base_url
        return result

    async def refresh(self, provider: str, credentials: dict) -> dict:
        refresh_token = str(credentials.get("refresh_token") or "")
        refresh_key = str(credentials.get("refresh_key") or "")
        if not refresh_token or not refresh_key:
            return credentials
        payload = {"refresh_token": refresh_token, "refresh_key": refresh_key}
        if provider == "ebay":
            payload["environment"] = "production"
            payload["scopes"] = credentials.get("scopes") or []
        data = await self._post(f"/api/{provider}/oauth/refresh", payload)
        updated = dict(credentials)
        updated.update(data)
        updated["expires_at"] = time.time() + int(data.get("expires_in") or (7200 if provider == "ebay" else 3600))
        return updated

    async def ensure_fresh(self, provider: str, credentials: dict) -> dict:
        expires_at = float(credentials.get("expires_at") or 0)
        if credentials.get("refresh_token") and credentials.get("refresh_key") and (
            not credentials.get("access_token") or expires_at <= time.time() + 180
        ):
            return await self.refresh(provider, credentials)
        return credentials

    async def etsy_request(
        self,
        credentials: dict,
        method: str,
        path: str,
        *,
        params: dict | None = None,
        form: dict | None = None,
        json_data: dict | None = None,
    ) -> dict:
        payload = {
            "access_token": credentials["access_token"],
            "broker_key": credentials["broker_key"],
            "method": method.upper(),
            "path": path,
            "params": params or {},
            "form": form,
            "json": json_data,
        }
        try:
            return await self._post("/api/etsy/api/request", payload, timeout=90)
        except RuntimeError:
            if method.upper() != "GET":
                raise
            return await self._post(
                "/api/etsy/api/get",
                {
                    "access_token": credentials["access_token"],
                    "broker_key": credentials["broker_key"],
                    "path": path,
                    "params": params or {},
                },
                timeout=90,
            )

    async def etsy_get(self, credentials: dict, path: str, params: dict | None = None) -> dict:
        return await self.etsy_request(credentials, "GET", path, params=params)
