from __future__ import annotations

import base64
import json
import time

import httpx


class EtsyOAuthBroker:
    def __init__(self, base_url: str, timeout: float = 30):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    @staticmethod
    def parse_authorization_result(value: str) -> dict[str, str]:
        raw = value.strip()
        if not raw:
            raise ValueError("Paste the authorization result copied from the Etsy approval page")
        payload_part = raw.split(".", 1)[0]
        try:
            padded = payload_part + "=" * (-len(payload_part) % 4)
            payload = json.loads(base64.urlsafe_b64decode(padded).decode())
        except Exception as exc:
            raise ValueError("Invalid Etsy authorization result; select Connect Etsy and try again") from exc
        if payload.get("provider") not in {None, "etsy"}:
            raise ValueError("That authorization result is not for Etsy")
        if not payload.get("code") or not payload.get("state"):
            raise ValueError("The Etsy authorization result is missing its code or state")
        payload["authorization_result"] = raw
        return payload

    async def start(self, state: str) -> dict:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(f"{self.base_url}/api/etsy/oauth/start", json={"state": state})
            response.raise_for_status()
            payload = response.json()
        url = str(payload.get("authorization_url", ""))
        verifier = str(payload.get("code_verifier", ""))
        if not url.startswith("https://www.etsy.com/") or not verifier:
            raise RuntimeError("Shop Sync Etsy sign-in service returned an invalid OAuth response")
        return {"authorization_url": url, "code_verifier": verifier}

    async def exchange(self, authorization_result: str, code_verifier: str) -> dict:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/api/etsy/oauth/exchange",
                json={"authorization_result": authorization_result, "code_verifier": code_verifier},
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
        if payload.get("refresh_token"):
            updated["refresh_token"] = payload["refresh_token"]
        if payload.get("refresh_key"):
            updated["refresh_key"] = payload["refresh_key"]
        return updated

    async def get(self, access_token: str, path: str, params: dict | None = None) -> dict:
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                f"{self.base_url}/api/etsy/proxy/get",
                json={"access_token": access_token, "path": path, "params": params or {}},
            )
            response.raise_for_status()
            return response.json()
