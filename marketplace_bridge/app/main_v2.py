from __future__ import annotations

import secrets as token_secrets
import time

import httpx
from fastapi import Form, HTTPException

from . import main as legacy
from .ebay import EbayClient, EbayListingUnavailable
from .ebay_broker import EbayOAuthBroker, parse_authorization_result
from .settings import settings

app = legacy.app
app.version = "0.0.25"
broker = EbayOAuthBroker(settings.ebay_oauth_broker_url)
_legacy_ensure_ebay_access_token = legacy.ensure_ebay_access_token


def _drop_route(path: str, method: str) -> None:
    method = method.upper()
    app.router.routes[:] = [
        route
        for route in app.router.routes
        if not (getattr(route, "path", None) == path and method in (getattr(route, "methods", set()) or set()))
    ]


_drop_route("/api/oauth/ebay/start", "POST")
_drop_route("/api/oauth/ebay/finish", "POST")


@app.post("/api/oauth/ebay/start")
async def start_ebay_oauth():
    state = token_secrets.token_urlsafe(32)
    legacy.save_credentials("ebay_oauth", {"state": state, "created_at": time.time()})
    try:
        authorization_url = await broker.start(state, settings.ebay_environment)
    except httpx.HTTPStatusError as exc:
        legacy.log.warning("eBay OAuth broker start failed with HTTP %s", exc.response.status_code)
        raise HTTPException(502, "Shop Sync could not start eBay sign-in; try again shortly") from exc
    except (RuntimeError, ValueError) as exc:
        legacy.log.warning("eBay OAuth broker start failed: %s", exc)
        raise HTTPException(502, str(exc)) from exc
    return {"authorization_url": authorization_url}


@app.post("/api/oauth/ebay/finish")
async def finish_ebay_oauth(oauth_result: str = Form(...)):
    pending = legacy.get_credentials("ebay_oauth")
    if time.time() - float(pending.get("created_at", 0)) > 900:
        legacy.db.delete_credential("ebay_oauth")
        raise HTTPException(400, "eBay connection expired; select Connect eBay and start again")

    try:
        result = parse_authorization_result(oauth_result)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    if not token_secrets.compare_digest(str(result.get("state", "")), str(pending.get("state", ""))):
        raise HTTPException(400, "eBay authorization state did not match; start the connection again")

    try:
        payload = await broker.exchange(result["authorization_result"], settings.ebay_environment)
        credentials = {
            "access_token": payload["access_token"],
            "refresh_token": payload.get("refresh_token", ""),
            "refresh_key": payload.get("refresh_key", ""),
            "expires_at": time.time() + int(payload.get("expires_in", 7200)),
            "refresh_token_expires_at": time.time() + int(payload.get("refresh_token_expires_in", 0)),
            "scopes": list(payload.get("scopes", [])),
            "oauth_mode": "publisher_broker",
        }
        client = EbayClient(credentials["access_token"], settings.ebay_environment)
        await client.list_active_ids()
    except httpx.HTTPStatusError as exc:
        legacy.log.warning("eBay OAuth broker exchange failed with HTTP %s", exc.response.status_code)
        raise HTTPException(502, "eBay connection failed; select Connect eBay and try again") from exc
    except (KeyError, RuntimeError, ValueError) as exc:
        legacy.log.warning("eBay OAuth connection failed: %s", exc)
        raise HTTPException(400, str(exc)) from exc

    legacy.save_credentials("ebay", credentials)
    legacy.db.delete_credential("ebay_oauth")
    return {"connected": True}


async def _ensure_ebay_access_token(credentials: dict, environment: str = "production") -> dict:
    if credentials.get("oauth_mode") == "publisher_broker":
        return await broker.ensure_access_token(credentials, environment)
    return await _legacy_ensure_ebay_access_token(credentials, environment)


legacy.ensure_ebay_access_token = _ensure_ebay_access_token


async def run_ebay_import(job_id: int):
    try:
        legacy.db.update_job(job_id, status="running", message="Reading active eBay listings")
        credential = legacy.get_credentials("ebay")
        credential = await _ensure_ebay_access_token(credential, settings.ebay_environment)
        legacy.save_credentials("ebay", credential)
        client = EbayClient(credential["access_token"], settings.ebay_environment)
        ids = await client.list_active_ids()
        legacy.db.update_job(job_id, total=len(ids), message=f"Found {len(ids)} listings")

        imported = 0
        skipped = 0
        for index, item_id in enumerate(ids, 1):
            try:
                product = await client.get_product(item_id)
            except EbayListingUnavailable as exc:
                skipped += 1
                legacy.log.info("Skipping unavailable eBay listing %s: %s", item_id, exc)
                legacy.db.update_job(
                    job_id,
                    progress=index,
                    message=f"Skipped unavailable eBay listing {item_id}; continuing",
                )
                continue

            legacy.db.save_product(product)
            imported += 1
            legacy.db.update_job(job_id, progress=index, message=f"Imported {product.title}")

        message = f"Imported {imported} listings"
        if skipped:
            message += f"; skipped {skipped} removed/unavailable listing{'s' if skipped != 1 else ''}"
        legacy.db.update_job(job_id, status="complete", progress=len(ids), message=message)
    except Exception as exc:
        legacy.log.exception("eBay import failed")
        legacy.db.update_job(job_id, status="failed", message=str(exc)[:500])


legacy.run_ebay_import = run_ebay_import


_original_render_dashboard = legacy.render_dashboard


def render_dashboard(*args, **kwargs):
    page = _original_render_dashboard(*args, **kwargs)
    old = '''<form method="post" action="api/oauth/ebay/start" onsubmit="startEbay(event)"><label>App ID (Client ID)</label><input name="client_id" type="password" required autocomplete="off"><label>Cert ID (Client secret)</label><input name="client_secret" type="password" required autocomplete="off"><label>RuName (eBay Redirect URL name)</label><input name="runame" type="password" required autocomplete="off"><button>Connect eBay</button></form>
    <form method="post" action="api/oauth/ebay/finish" onsubmit="connect(event)"><label>eBay callback URL</label><input name="oauth_result" required autocomplete="off" placeholder="Paste the full callback URL after approving eBay"><button>Finish eBay connection</button></form><small>Shop Sync stores the refresh token encrypted and renews the short-lived eBay access token automatically. Keep the Cert ID and tokens private.</small>'''
    new = '''<form method="post" action="api/oauth/ebay/start" onsubmit="startEbay(event)"><button>Connect eBay</button></form>
    <form method="post" action="api/oauth/ebay/finish" onsubmit="connect(event)"><label>Authorization result</label><input name="oauth_result" required autocomplete="off" placeholder="Paste the result copied after eBay approval"><button>Finish eBay connection</button></form><small>No eBay developer account is required. Sign in to your seller account, approve Shop Sync, copy the authorization result, and paste it here. Tokens are stored locally and refreshed automatically.</small>'''
    return page.replace(old, new)


legacy.render_dashboard = render_dashboard
