from __future__ import annotations

import base64
import hashlib
import hmac
import html
import json
import os
import time
from urllib.parse import urlencode

import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

app = FastAPI(title="Shop Sync eBay OAuth Broker", version="1.0")

CLIENT_ID = os.environ.get("EBAY_CLIENT_ID", "").strip()
CLIENT_SECRET = os.environ.get("EBAY_CLIENT_SECRET", "").strip()
RUNAME = os.environ.get("EBAY_RUNAME", "").strip()
SIGNING_SECRET = os.environ.get("BROKER_SIGNING_SECRET", "").encode() or hashlib.sha256(
    (CLIENT_SECRET + ":shop-sync-broker").encode()
).digest()

SCOPES = (
    "https://api.ebay.com/oauth/api_scope",
    "https://api.ebay.com/oauth/api_scope/sell.inventory",
)


def _require_config() -> None:
    if not CLIENT_ID or not CLIENT_SECRET or not RUNAME:
        raise HTTPException(503, "eBay OAuth broker is not configured")


def _hosts(environment: str) -> tuple[str, str]:
    if environment == "sandbox":
        return "https://auth.sandbox.ebay.com", "https://api.sandbox.ebay.com"
    if environment != "production":
        raise HTTPException(400, "Invalid eBay environment")
    return "https://auth.ebay.com", "https://api.ebay.com"


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64url(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _sign(payload: str) -> str:
    return _b64url(hmac.new(SIGNING_SECRET, payload.encode(), hashlib.sha256).digest())


def _signed_result(payload: dict) -> str:
    encoded = _b64url(json.dumps(payload, separators=(",", ":")).encode())
    return f"{encoded}.{_sign(encoded)}"


def _verify_result(value: str, max_age: int = 900) -> dict:
    try:
        payload_part, signature = value.strip().split(".", 1)
        if not hmac.compare_digest(signature, _sign(payload_part)):
            raise ValueError("signature")
        payload = json.loads(_unb64url(payload_part).decode())
        if time.time() - float(payload.get("iat", 0)) > max_age:
            raise ValueError("expired")
        if not payload.get("code") or not payload.get("state"):
            raise ValueError("missing fields")
        return payload
    except Exception as exc:
        raise HTTPException(400, "Invalid or expired eBay authorization result") from exc


def _refresh_key(refresh_token: str) -> str:
    return _b64url(hmac.new(SIGNING_SECRET, ("refresh:" + refresh_token).encode(), hashlib.sha256).digest())


def _basic_auth() -> str:
    encoded = base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()
    return f"Basic {encoded}"


class StartRequest(BaseModel):
    state: str
    environment: str = "production"


class ExchangeRequest(BaseModel):
    authorization_result: str
    environment: str = "production"


class RefreshRequest(BaseModel):
    refresh_token: str
    refresh_key: str
    scopes: list[str] = []
    environment: str = "production"


@app.get("/health")
def health():
    return {"status": "ok", "configured": bool(CLIENT_ID and CLIENT_SECRET and RUNAME)}


@app.post("/api/ebay/oauth/start")
def start_oauth(request: StartRequest):
    _require_config()
    auth_host, _ = _hosts(request.environment)
    query = urlencode(
        {
            "client_id": CLIENT_ID,
            "response_type": "code",
            "redirect_uri": RUNAME,
            "scope": " ".join(SCOPES),
            "state": request.state,
        }
    )
    return {"authorization_url": f"{auth_host}/oauth2/authorize?{query}"}


@app.get("/api/ebay/oauth/callback", response_class=HTMLResponse)
def callback(
    code: str = Query(default=""),
    state: str = Query(default=""),
    error: str = Query(default=""),
    error_description: str = Query(default=""),
):
    if error:
        message = html.escape(error_description or error)
        return HTMLResponse(
            f"<!doctype html><html><body><h1>eBay connection declined</h1><p>{message}</p></body></html>",
            status_code=400,
        )
    if not code or not state:
        return HTMLResponse(
            "<!doctype html><html><body><h1>Invalid eBay callback</h1><p>The authorization code or state is missing.</p></body></html>",
            status_code=400,
        )
    result = _signed_result({"code": code, "state": state, "iat": int(time.time())})
    safe_result = html.escape(result, quote=True)
    return HTMLResponse(
        f'''<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>Shop Sync eBay approved</title>
<style>body{{font:16px system-ui,sans-serif;max-width:680px;margin:50px auto;padding:20px}}button{{font-size:17px;padding:12px 18px;cursor:pointer}}code{{word-break:break-all}}</style></head><body>
<h1>eBay approved</h1><p>Return to Shop Sync after copying this one-time authorization result.</p>
<button id="copy">Copy authorization result</button><p id="status"></p>
<script>const value={json.dumps(result)};document.getElementById('copy').onclick=async()=>{{await navigator.clipboard.writeText(value);document.getElementById('status').textContent='Copied. Return to Shop Sync and paste it into Authorization result.';}};</script>
<noscript><code>{safe_result}</code></noscript></body></html>'''
    )


@app.post("/api/ebay/oauth/exchange")
async def exchange(request: ExchangeRequest):
    _require_config()
    payload = _verify_result(request.authorization_result)
    _, api_host = _hosts(request.environment)
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            f"{api_host}/identity/v1/oauth2/token",
            headers={"Authorization": _basic_auth(), "Content-Type": "application/x-www-form-urlencoded"},
            data={"grant_type": "authorization_code", "code": payload["code"], "redirect_uri": RUNAME},
        )
        if response.status_code >= 400:
            raise HTTPException(502, "eBay rejected the authorization-code exchange")
        token = response.json()
    refresh_token = token.get("refresh_token", "")
    return {
        "access_token": token["access_token"],
        "refresh_token": refresh_token,
        "refresh_key": _refresh_key(refresh_token) if refresh_token else "",
        "expires_in": token.get("expires_in", 7200),
        "refresh_token_expires_in": token.get("refresh_token_expires_in", 0),
        "scopes": list(SCOPES),
    }


@app.post("/api/ebay/oauth/refresh")
async def refresh(request: RefreshRequest):
    _require_config()
    if not request.refresh_token or not hmac.compare_digest(request.refresh_key, _refresh_key(request.refresh_token)):
        raise HTTPException(401, "Invalid Shop Sync refresh credential")
    _, api_host = _hosts(request.environment)
    scopes = request.scopes or list(SCOPES)
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            f"{api_host}/identity/v1/oauth2/token",
            headers={"Authorization": _basic_auth(), "Content-Type": "application/x-www-form-urlencoded"},
            data={"grant_type": "refresh_token", "refresh_token": request.refresh_token, "scope": " ".join(scopes)},
        )
        if response.status_code >= 400:
            raise HTTPException(502, "eBay rejected the refresh-token request")
        token = response.json()
    new_refresh = token.get("refresh_token") or request.refresh_token
    return {
        "access_token": token["access_token"],
        "refresh_token": new_refresh,
        "refresh_key": _refresh_key(new_refresh),
        "expires_in": token.get("expires_in", 7200),
    }
