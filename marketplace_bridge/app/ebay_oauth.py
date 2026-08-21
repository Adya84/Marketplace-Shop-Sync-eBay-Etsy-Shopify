from __future__ import annotations

import base64
import time
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

EBAY_SCOPES = (
    "https://api.ebay.com/oauth/api_scope",
    "https://api.ebay.com/oauth/api_scope/sell.inventory",
)


def _hosts(environment: str) -> tuple[str, str]:
    if environment == "sandbox":
        return "https://auth.sandbox.ebay.com", "https://api.sandbox.ebay.com"
    return "https://auth.ebay.com", "https://api.ebay.com"


def authorization_url(client_id: str, runame: str, state: str, environment: str = "production") -> str:
    auth_host, _ = _hosts(environment)
    query = urlencode({
        "client_id": client_id.strip(),
        "response_type": "code",
        "redirect_uri": runame.strip(),
        "scope": " ".join(EBAY_SCOPES),
        "state": state,
    })
    return f"{auth_host}/oauth2/authorize?{query}"


def parse_callback_result(value: str) -> dict[str, str]:
    raw = value.strip()
    if not raw:
        raise ValueError("Paste the full eBay callback URL")
    if "://" not in raw:
        raise ValueError("Paste the full callback URL shown after eBay approval")
    parsed = urlparse(raw)
    values = parse_qs(parsed.query, keep_blank_values=True)
    result = {key: entries[0] for key, entries in values.items() if entries}
    if result.get("error"):
        raise ValueError(result.get("error_description") or result["error"])
    if not result.get("code"):
        raise ValueError("The callback URL does not contain an eBay authorization code")
    if not result.get("state"):
        raise ValueError("The callback URL does not contain the OAuth state value")
    return result


def _basic_auth(client_id: str, client_secret: str) -> str:
    encoded = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    return f"Basic {encoded}"


async def exchange_code(
    client_id: str,
    client_secret: str,
    code: str,
    runame: str,
    environment: str = "production",
) -> dict:
    _, api_host = _hosts(environment)
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            f"{api_host}/identity/v1/oauth2/token",
            headers={
                "Authorization": _basic_auth(client_id, client_secret),
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": runame,
            },
        )
        response.raise_for_status()
        return response.json()


async def refresh_access_token(credentials: dict, environment: str = "production") -> dict:
    refresh_token = credentials.get("refresh_token", "")
    if not refresh_token:
        return credentials
    _, api_host = _hosts(environment)
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            f"{api_host}/identity/v1/oauth2/token",
            headers={
                "Authorization": _basic_auth(credentials["client_id"], credentials["client_secret"]),
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "scope": " ".join(credentials.get("scopes") or EBAY_SCOPES),
            },
        )
        response.raise_for_status()
        payload = response.json()
    updated = dict(credentials)
    updated["access_token"] = payload["access_token"]
    updated["expires_at"] = time.time() + int(payload.get("expires_in", 7200))
    return updated


async def ensure_access_token(credentials: dict, environment: str = "production") -> dict:
    expires_at = float(credentials.get("expires_at", 0) or 0)
    if credentials.get("refresh_token") and (not credentials.get("access_token") or expires_at <= time.time() + 120):
        return await refresh_access_token(credentials, environment)
    return credentials
