from __future__ import annotations

import secrets as token_secrets
import time

import httpx
from fastapi import Form, HTTPException
from fastapi.responses import HTMLResponse

from . import main as core
from . import main_v3 as v3
from .etsy_broker import BrokerEtsyClient, EtsyOAuthBroker, parse_authorization_result
from .settings import settings

app = v3.app
app.version = "0.0.29"
etsy_broker = EtsyOAuthBroker(settings.ebay_oauth_broker_url)


def _drop_route(path: str, method: str) -> None:
    method = method.upper()
    app.router.routes[:] = [
        route
        for route in app.router.routes
        if not (getattr(route, "path", None) == path and method in (getattr(route, "methods", set()) or set()))
    ]


_drop_route("/api/oauth/etsy/start", "POST")
_drop_route("/api/oauth/etsy/finish", "POST")


@app.post("/api/oauth/etsy/start")
async def start_etsy_oauth():
    state = token_secrets.token_urlsafe(32)
    core.save_credentials("etsy_oauth", {"state": state, "created_at": time.time()})
    try:
        authorization_url = await etsy_broker.start(state)
    except httpx.HTTPStatusError as exc:
        core.log.warning("Etsy OAuth broker start failed with HTTP %s", exc.response.status_code)
        raise HTTPException(502, "Shop Sync could not start Etsy sign-in; try again shortly") from exc
    except (RuntimeError, ValueError) as exc:
        core.log.warning("Etsy OAuth broker start failed: %s", exc)
        raise HTTPException(502, str(exc)) from exc
    return {"authorization_url": authorization_url}


@app.post("/api/oauth/etsy/finish")
async def finish_etsy_oauth(oauth_result: str = Form(...)):
    pending = core.get_credentials("etsy_oauth")
    if time.time() - float(pending.get("created_at", 0)) > 900:
        core.db.delete_credential("etsy_oauth")
        raise HTTPException(400, "Etsy connection expired; select Connect Etsy and start again")

    try:
        result = parse_authorization_result(oauth_result)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    if not token_secrets.compare_digest(str(result.get("state", "")), str(pending.get("state", ""))):
        raise HTTPException(400, "Etsy authorization state did not match; start the connection again")

    try:
        payload = await etsy_broker.exchange(result["authorization_result"])
        credentials = {
            "shop_id": "pending",
            "access_token": payload["access_token"],
            "refresh_token": payload.get("refresh_token", ""),
            "expires_at": time.time() + int(payload.get("expires_in", 3600)),
            "broker_key": payload["broker_key"],
            "refresh_key": payload.get("refresh_key", ""),
            "broker_url": settings.ebay_oauth_broker_url,
            "oauth_mode": "publisher_broker",
        }
        client = BrokerEtsyClient(**credentials)
        shop = await client.find_authorised_shop()
        client.shop_id = str(shop["shop_id"])
        credentials = client.credential_payload()
    except httpx.HTTPStatusError as exc:
        core.log.warning("Etsy OAuth broker exchange failed with HTTP %s", exc.response.status_code)
        raise HTTPException(502, "Etsy connection failed; select Connect Etsy and try again") from exc
    except (KeyError, RuntimeError, ValueError) as exc:
        core.log.warning("Etsy OAuth connection failed: %s", exc)
        raise HTTPException(400, str(exc)) from exc

    core.save_credentials("etsy", credentials)
    core.db.delete_credential("etsy_oauth")
    return {"connected": True, "shop": shop.get("shop_name", credentials["shop_id"])}


async def run_etsy_import(job_id: int):
    try:
        core.db.update_job(job_id, status="running", message="Reading active Etsy listings")
        credential = core.get_credentials("etsy")
        if credential.get("oauth_mode") == "publisher_broker":
            client = BrokerEtsyClient(**credential)
        else:
            client = core.EtsyClient(**credential)
        ids = await client.list_active_ids()
        core.save_credentials("etsy", client.credential_payload())
        core.db.update_job(job_id, total=len(ids), message=f"Found {len(ids)} listings")
        for index, listing_id in enumerate(ids, 1):
            product = await client.get_product(listing_id)
            core.db.save_product(product)
            core.save_credentials("etsy", client.credential_payload())
            core.db.update_job(job_id, progress=index, message=f"Imported {product.title}")
        core.db.update_job(
            job_id,
            status="complete",
            progress=len(ids),
            message=f"Imported {len(ids)} listings",
        )
    except Exception as exc:
        core.log.exception("Etsy import failed")
        core.db.update_job(job_id, status="failed", message=str(exc)[:500])


core.run_etsy_import = run_etsy_import


_drop_route("/", "GET")


@app.get("/", response_class=HTMLResponse)
def dashboard():
    response = v3.dashboard()
    page = response.body.decode("utf-8")
    old = '''<form method="post" action="api/oauth/etsy/start" onsubmit="startEtsy(event)"><label>API keystring</label><input name="keystring" type="password" required autocomplete="off"><label>Shared secret</label><input name="shared_secret" type="password" required autocomplete="off"><button>Connect Etsy</button></form>
    <form method="post" action="api/oauth/etsy/finish" onsubmit="connect(event)" class="etsy-finish"><label>Authorization result</label><input name="oauth_result" required autocomplete="off" placeholder="Paste the result copied from the Etsy approval page"><button>Finish Etsy connection</button></form><small>Tokens and Shop ID are created automatically. Never paste them into chat or screenshots.</small>'''
    new = '''<form method="post" action="api/oauth/etsy/start" onsubmit="startEtsy(event)"><button>Connect Etsy</button></form>
    <form method="post" action="api/oauth/etsy/finish" onsubmit="connect(event)" class="etsy-finish"><label>Authorization result</label><input name="oauth_result" required autocomplete="off" placeholder="Paste the result copied after Etsy approval"><button>Finish Etsy connection</button></form><small>No Etsy developer credentials are required. Sign in to your Etsy seller account, approve Shop Sync, copy the authorization result, and paste it here. Tokens are stored locally and refreshed automatically.</small>'''
    page = page.replace(old, new)
    return HTMLResponse(page)
