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

app = FastAPI(title="Shop Sync OAuth Broker", version="1.1")

EBAY_CLIENT_ID = os.environ.get("EBAY_CLIENT_ID", "").strip()
EBAY_CLIENT_SECRET = os.environ.get("EBAY_CLIENT_SECRET", "").strip()
EBAY_RUNAME = os.environ.get("EBAY_RUNAME", "").strip()

ETSY_KEYSTRING = os.environ.get("ETSY_KEYSTRING", "").strip()
ETSY_SHARED_SECRET = os.environ.get("ETSY_SHARED_SECRET", "").strip()
ETSY_REDIRECT_URI = os.environ.get(
    "ETSY_REDIRECT_URI",
    "https://shop-sync-ebay-compliance.zesty-flame-5295.chatgpt.site/api/etsy/oauth/callback",
).strip()

_seed = os.environ.get("BROKER_SIGNING_SECRET", "").strip()
if _seed:
    SIGNING_SECRET = _seed.encode()
else:
    SIGNING_SECRET = hashlib.sha256(
        (EBAY_CLIENT_SECRET + ":" + ETSY_SHARED_SECRET + ":shop-sync-broker").encode()
    ).digest()

EBAY_SCOPES = (
    "https://api.ebay.com/oauth/api_scope",
    "https://api.ebay.com/oauth/api_scope/sell.inventory",
)
ETSY_SCOPES = ("listings_r", "listings_w", "shops_r")


def _require_ebay_config() -> None:
    if not EBAY_CLIENT_ID or not EBAY_CLIENT_SECRET or not EBAY_RUNAME:
        raise HTTPException(503, "eBay OAuth broker is not configured")


def _require_etsy_config() -> None:
    if not ETSY_KEYSTRING or not ETSY_SHARED_SECRET or not ETSY_REDIRECT_URI:
        raise HTTPException(503, "Etsy OAuth broker is not configured")


def _ebay_hosts(environment: str) -> tuple[str, str]:
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


def _verify_signed(value: str, max_age: int = 900) -> dict:
    try:
        payload_part, signature = value.strip().split(".", 1)
        if not hmac.compare_digest(signature, _sign(payload_part)):
            raise ValueError("signature")
        payload = json.loads(_unb64url(payload_part).decode())
        if time.time() - float(payload.get("iat", 0)) > max_age:
            raise ValueError("expired")
        return payload
    except Exception as exc:
        raise HTTPException(400, "Invalid or expired authorization result") from exc


def _verify_ebay_result(value: str, max_age: int = 900) -> dict:
    payload = _verify_signed(value, max_age)
    if not payload.get("code") or not payload.get("state"):
        raise HTTPException(400, "Invalid or expired eBay authorization result")
    return payload


def _refresh_key(provider: str, refresh_token: str) -> str:
    return _b64url(
        hmac.new(SIGNING_SECRET, f"{provider}:refresh:{refresh_token}".encode(), hashlib.sha256).digest()
    )


def _etsy_broker_key(access_token: str) -> str:
    return _b64url(
        hmac.new(SIGNING_SECRET, f"etsy:api:{access_token}".encode(), hashlib.sha256).digest()
    )


def _ebay_basic_auth() -> str:
    encoded = base64.b64encode(f"{EBAY_CLIENT_ID}:{EBAY_CLIENT_SECRET}".encode()).decode()
    return f"Basic {encoded}"


def _approval_page(provider: str, result: str) -> HTMLResponse:
    safe_result = html.escape(result, quote=True)
    safe_provider = html.escape(provider)
    return HTMLResponse(
        f'''<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>Shop Sync {safe_provider} approved</title>
<style>body{{font:16px system-ui,sans-serif;max-width:680px;margin:50px auto;padding:20px}}button{{font-size:17px;padding:12px 18px;cursor:pointer}}code{{word-break:break-all}}</style></head><body>
<h1>{safe_provider} approved</h1><p>Return to Shop Sync after copying this one-time authorization result.</p>
<button id="copy">Copy authorization result</button><p id="status"></p>
<script>const value={json.dumps(result)};document.getElementById('copy').onclick=async()=>{{await navigator.clipboard.writeText(value);document.getElementById('status').textContent='Copied. Return to Shop Sync and paste it into Authorization result.';}};</script>
<noscript><code>{safe_result}</code></noscript></body></html>'''
    )


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


class EtsyApiGetRequest(BaseModel):
    access_token: str
    broker_key: str
    path: str
    params: dict = {}


@app.get("/health")
def health():
    return {
        "status": "ok",
        "ebay_configured": bool(EBAY_CLIENT_ID and EBAY_CLIENT_SECRET and EBAY_RUNAME),
        "etsy_configured": bool(ETSY_KEYSTRING and ETSY_SHARED_SECRET and ETSY_REDIRECT_URI),
    }


@app.post("/api/ebay/oauth/start")
def start_ebay_oauth(request: StartRequest):
    _require_ebay_config()
    auth_host, _ = _ebay_hosts(request.environment)
    query = urlencode(
        {
            "client_id": EBAY_CLIENT_ID,
            "response_type": "code",
            "redirect_uri": EBAY_RUNAME,
            "scope": " ".join(EBAY_SCOPES),
            "state": request.state,
        }
    )
    return {"authorization_url": f"{auth_host}/oauth2/authorize?{query}"}


@app.get("/api/ebay/oauth/callback", response_class=HTMLResponse)
def ebay_callback(
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
    result = _signed_result({"code": code, "state": state, "iat": int(time.time()), "kind": "ebay_auth"})
    return _approval_page("eBay", result)


@app.post("/api/ebay/oauth/exchange")
async def exchange_ebay(request: ExchangeRequest):
    _require_ebay_config()
    payload = _verify_ebay_result(request.authorization_result)
    _, api_host = _ebay_hosts(request.environment)
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            f"{api_host}/identity/v1/oauth2/token",
            headers={"Authorization": _ebay_basic_auth(), "Content-Type": "application/x-www-form-urlencoded"},
            data={"grant_type": "authorization_code", "code": payload["code"], "redirect_uri": EBAY_RUNAME},
        )
        if response.status_code >= 400:
            raise HTTPException(502, "eBay rejected the authorization-code exchange")
        token = response.json()
    refresh_token = token.get("refresh_token", "")
    return {
        "access_token": token["access_token"],
        "refresh_token": refresh_token,
        "refresh_key": _refresh_key("ebay", refresh_token) if refresh_token else "",
        "expires_in": token.get("expires_in", 7200),
        "refresh_token_expires_in": token.get("refresh_token_expires_in", 0),
        "scopes": list(EBAY_SCOPES),
    }


@app.post("/api/ebay/oauth/refresh")
async def refresh_ebay(request: RefreshRequest):
    _require_ebay_config()
    if not request.refresh_token or not hmac.compare_digest(
        request.refresh_key, _refresh_key("ebay", request.refresh_token)
    ):
        raise HTTPException(401, "Invalid Shop Sync refresh credential")
    _, api_host = _ebay_hosts(request.environment)
    scopes = request.scopes or list(EBAY_SCOPES)
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            f"{api_host}/identity/v1/oauth2/token",
            headers={"Authorization": _ebay_basic_auth(), "Content-Type": "application/x-www-form-urlencoded"},
            data={"grant_type": "refresh_token", "refresh_token": request.refresh_token, "scope": " ".join(scopes)},
        )
        if response.status_code >= 400:
            raise HTTPException(502, "eBay rejected the refresh-token request")
        token = response.json()
    new_refresh = token.get("refresh_token") or request.refresh_token
    return {
        "access_token": token["access_token"],
        "refresh_token": new_refresh,
        "refresh_key": _refresh_key("ebay", new_refresh),
        "expires_in": token.get("expires_in", 7200),
    }


@app.post("/api/etsy/oauth/start")
def start_etsy_oauth(request: StartRequest):
    _require_etsy_config()
    if not request.state:
        raise HTTPException(400, "OAuth state is required")
    verifier = _b64url(os.urandom(48))
    challenge = _b64url(hashlib.sha256(verifier.encode()).digest())
    broker_state = _signed_result(
        {"state": request.state, "verifier": verifier, "iat": int(time.time()), "kind": "etsy_state"}
    )
    query = urlencode(
        {
            "response_type": "code",
            "client_id": ETSY_KEYSTRING,
            "redirect_uri": ETSY_REDIRECT_URI,
            "scope": " ".join(ETSY_SCOPES),
            "state": broker_state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
    )
    return {"authorization_url": f"https://www.etsy.com/oauth/connect?{query}"}


@app.get("/api/etsy/oauth/callback", response_class=HTMLResponse)
def etsy_callback(
    code: str = Query(default=""),
    state: str = Query(default=""),
    error: str = Query(default=""),
    error_description: str = Query(default=""),
):
    if error:
        message = html.escape(error_description or error)
        return HTMLResponse(
            f"<!doctype html><html><body><h1>Etsy connection declined</h1><p>{message}</p></body></html>",
            status_code=400,
        )
    if not code or not state:
        return HTMLResponse(
            "<!doctype html><html><body><h1>Invalid Etsy callback</h1><p>The authorization code or state is missing.</p></body></html>",
            status_code=400,
        )
    state_payload = _verify_signed(state)
    if state_payload.get("kind") != "etsy_state" or not state_payload.get("state") or not state_payload.get("verifier"):
        raise HTTPException(400, "Invalid or expired Etsy authorization state")
    result = _signed_result(
        {
            "code": code,
            "state": state_payload["state"],
            "verifier": state_payload["verifier"],
            "iat": int(time.time()),
            "kind": "etsy_auth",
        }
    )
    return _approval_page("Etsy", result)


@app.post("/api/etsy/oauth/exchange")
async def exchange_etsy(request: ExchangeRequest):
    _require_etsy_config()
    payload = _verify_signed(request.authorization_result)
    if payload.get("kind") != "etsy_auth" or not payload.get("code") or not payload.get("verifier"):
        raise HTTPException(400, "Invalid or expired Etsy authorization result")
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            "https://api.etsy.com/v3/public/oauth/token",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                "grant_type": "authorization_code",
                "client_id": ETSY_KEYSTRING,
                "redirect_uri": ETSY_REDIRECT_URI,
                "code": payload["code"],
                "code_verifier": payload["verifier"],
            },
        )
        if response.status_code >= 400:
            raise HTTPException(502, "Etsy rejected the authorization-code exchange")
        token = response.json()
    access_token = token["access_token"]
    refresh_token = token.get("refresh_token", "")
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "refresh_key": _refresh_key("etsy", refresh_token) if refresh_token else "",
        "broker_key": _etsy_broker_key(access_token),
        "expires_in": token.get("expires_in", 3600),
        "scopes": str(token.get("scope", "")).split(),
    }


@app.post("/api/etsy/oauth/refresh")
async def refresh_etsy(request: RefreshRequest):
    _require_etsy_config()
    if not request.refresh_token or not hmac.compare_digest(
        request.refresh_key, _refresh_key("etsy", request.refresh_token)
    ):
        raise HTTPException(401, "Invalid Shop Sync Etsy refresh credential")
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            "https://api.etsy.com/v3/public/oauth/token",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                "grant_type": "refresh_token",
                "client_id": ETSY_KEYSTRING,
                "refresh_token": request.refresh_token,
            },
        )
        if response.status_code >= 400:
            raise HTTPException(502, "Etsy rejected the refresh-token request")
        token = response.json()
    access_token = token["access_token"]
    new_refresh = token.get("refresh_token") or request.refresh_token
    return {
        "access_token": access_token,
        "refresh_token": new_refresh,
        "refresh_key": _refresh_key("etsy", new_refresh),
        "broker_key": _etsy_broker_key(access_token),
        "expires_in": token.get("expires_in", 3600),
    }


@app.post("/api/etsy/api/get")
async def etsy_api_get(request: EtsyApiGetRequest):
    _require_etsy_config()
    if not request.access_token or not hmac.compare_digest(
        request.broker_key, _etsy_broker_key(request.access_token)
    ):
        raise HTTPException(401, "Invalid Shop Sync Etsy API credential")
    path = request.path.strip()
    if not path.startswith("/v3/application/") or "://" in path or ".." in path:
        raise HTTPException(400, "Invalid Etsy API path")
    headers = {
        "x-api-key": f"{ETSY_KEYSTRING}:{ETSY_SHARED_SECRET}",
        "Authorization": f"Bearer {request.access_token}",
    }
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.get(f"https://api.etsy.com{path}", params=request.params, headers=headers)
    if response.status_code >= 400:
        detail = response.text[:500] or "Etsy API request failed"
        raise HTTPException(response.status_code, detail)
    return response.json()
