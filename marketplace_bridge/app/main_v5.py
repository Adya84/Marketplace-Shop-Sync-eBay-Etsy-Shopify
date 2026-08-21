from __future__ import annotations

import secrets as token_secrets
import time

import httpx
from fastapi import Form, HTTPException
from fastapi.responses import HTMLResponse

from . import main as core
from . import main_v3 as v3
from . import main_v4 as v4
from .settings import settings
from .shopify import ShopifyClient
from .shopify_broker import ShopifyOAuthBroker, parse_authorization_result

app = v4.app
app.version = "0.0.30"
shopify_broker = ShopifyOAuthBroker(settings.ebay_oauth_broker_url)


def _drop_route(path: str, method: str) -> None:
    method = method.upper()
    app.router.routes[:] = [
        route
        for route in app.router.routes
        if not (getattr(route, "path", None) == path and method in (getattr(route, "methods", set()) or set()))
    ]


def _shopify_client(credential: dict) -> ShopifyClient:
    if credential.get("oauth_mode") == "publisher_oauth" or credential.get("access_token"):
        return ShopifyClient(
            credential["shop_domain"],
            settings.shopify_api_version,
            access_token=credential["access_token"],
        )
    return ShopifyClient(
        credential["shop_domain"],
        settings.shopify_api_version,
        client_id=credential["client_id"],
        client_secret=credential["client_secret"],
    )


_drop_route("/api/settings/shopify", "POST")


@app.post("/api/oauth/shopify/start")
async def start_shopify_oauth(shop_domain: str = Form(...)):
    shop_domain = shop_domain.strip().lower().removeprefix("https://").rstrip("/")
    if not shop_domain.endswith(".myshopify.com"):
        raise HTTPException(400, "Enter the permanent Shopify store domain ending in .myshopify.com")

    state = token_secrets.token_urlsafe(32)
    core.save_credentials(
        "shopify_oauth",
        {"shop_domain": shop_domain, "state": state, "created_at": time.time()},
    )
    try:
        authorization_url = await shopify_broker.start(shop_domain, state)
    except httpx.HTTPStatusError as exc:
        core.log.warning("Shopify OAuth broker start failed with HTTP %s", exc.response.status_code)
        raise HTTPException(502, "Shop Sync could not start Shopify sign-in; try again shortly") from exc
    except (RuntimeError, ValueError) as exc:
        core.log.warning("Shopify OAuth broker start failed: %s", exc)
        raise HTTPException(502, str(exc)) from exc
    return {"authorization_url": authorization_url}


@app.post("/api/oauth/shopify/finish")
async def finish_shopify_oauth(oauth_result: str = Form(...)):
    pending = core.get_credentials("shopify_oauth")
    if time.time() - float(pending.get("created_at", 0)) > 900:
        core.db.delete_credential("shopify_oauth")
        raise HTTPException(400, "Shopify connection expired; select Connect Shopify and start again")

    try:
        result = parse_authorization_result(oauth_result)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    if not token_secrets.compare_digest(str(result.get("state", "")), str(pending.get("state", ""))):
        raise HTTPException(400, "Shopify authorization state did not match; start the connection again")

    expected_shop = str(pending.get("shop_domain", "")).lower()
    if str(result.get("shop", "")).lower() != expected_shop:
        raise HTTPException(400, "Shopify authorization returned a different store; start the connection again")

    try:
        payload = await shopify_broker.exchange(result["authorization_result"])
        shop_domain = str(payload.get("shop") or expected_shop)
        credentials = {
            "shop_domain": shop_domain,
            "access_token": payload["access_token"],
            "scope": payload.get("scope", ""),
            "scopes": payload.get("scopes", []),
            "oauth_mode": "publisher_oauth",
        }
        client = _shopify_client(credentials)
        shop = await client.test()
        credentials["shop_domain"] = shop["myshopifyDomain"]
    except httpx.HTTPStatusError as exc:
        core.log.warning("Shopify OAuth exchange failed with HTTP %s", exc.response.status_code)
        raise HTTPException(502, "Shopify connection failed; select Connect Shopify and try again") from exc
    except (KeyError, RuntimeError, ValueError) as exc:
        core.log.warning("Shopify OAuth connection failed: %s", exc)
        raise HTTPException(400, str(exc)) from exc

    core.save_credentials("shopify", credentials)
    core.db.delete_credential("shopify_oauth")
    return {"connected": True, "shop": shop.get("name", credentials["shop_domain"])}


async def run_shopify_import(job_id: int):
    try:
        core.db.update_job(job_id, status="running", message="Reading Shopify catalogue")
        credential = core.get_credentials("shopify")
        client = _shopify_client(credential)
        products = await client.list_products()
        core.db.update_job(job_id, total=len(products), message=f"Found {len(products)} products")
        for index, product in enumerate(products, 1):
            core.db.save_product(product)
            core.db.update_job(job_id, progress=index, message=f"Imported {product.title}")
        core.db.update_job(
            job_id,
            status="complete",
            progress=len(products),
            message=f"Imported {len(products)} Shopify products",
        )
    except Exception as exc:
        core.log.exception("Shopify import failed")
        core.db.update_job(job_id, status="failed", message=str(exc)[:500])


async def run_shopify_export(job_id: int, source: str, source_id: str) -> bool:
    product = core.db.get_product(source, source_id)
    if not product:
        core.db.update_job(job_id, status="failed", total=1, message=f"Product not found: {source} {source_id}")
        return False
    title = str(product.get("title") or source_id)
    try:
        core.db.update_job(
            job_id,
            status="running",
            progress=0,
            total=1,
            message=f"Creating Shopify draft from {source.title()}: {title}",
        )
        credential = core.get_credentials("shopify")
        client = _shopify_client(credential)
        created = await client.create_draft(product)
        core.db.save_mapping(
            source,
            source_id,
            "shopify",
            created["id"],
            {"variants": created["variants"]["nodes"]},
        )
        core.db.update_job(
            job_id,
            status="complete",
            progress=1,
            total=1,
            message=f"Created Shopify draft: {created['title']}",
        )
        return True
    except Exception as exc:
        core.log.exception("Shopify export failed")
        core.db.update_job(
            job_id,
            status="failed",
            progress=0,
            total=1,
            message=f"{title}: {str(exc)[:430]}",
        )
        return False


core.run_shopify_import = run_shopify_import
core.run_shopify_export = run_shopify_export
v3._run_single_export = run_shopify_export


_drop_route("/", "GET")


@app.get("/", response_class=HTMLResponse)
def dashboard():
    response = v4.dashboard()
    page = response.body.decode("utf-8")
    old = '''<form method="post" action="api/settings/shopify" onsubmit="connect(event)"><label>Store domain</label><input name="shop_domain" placeholder="store.myshopify.com" required><label>Client ID</label><input name="client_id" type="password" required autocomplete="off"><label>Client secret</label><input name="client_secret" type="password" required autocomplete="off"><button>Test and save</button></form>'''
    new = '''<form method="post" action="api/oauth/shopify/start" onsubmit="startShopify(event)"><label>Store domain</label><input name="shop_domain" placeholder="store.myshopify.com" required autocomplete="off"><button>Connect Shopify</button></form>
    <form method="post" action="api/oauth/shopify/finish" onsubmit="connect(event)" class="shopify-finish"><label>Authorization result</label><input name="oauth_result" required autocomplete="off" placeholder="Paste the result copied after Shopify approval"><button>Finish Shopify connection</button></form><small>No Shopify developer credentials are required. Enter the permanent .myshopify.com store domain, approve Shop Sync in Shopify, copy the authorization result, and paste it here.</small>'''
    page = page.replace(old, new)

    script = r'''<script>
    async function startShopify(event){
      event.preventDefault();
      const form=event.currentTarget;
      const button=form.querySelector('button');
      const original=button.textContent;
      button.disabled=true; button.textContent='Opening Shopify…';
      try{
        const response=await fetch(form.action,{method:'POST',body:new FormData(form)});
        if(!response.ok)throw new Error(await response.text());
        const data=await response.json();
        if(!data.authorization_url)throw new Error('Shop Sync did not return a Shopify authorization URL');
        window.open(data.authorization_url,'_blank','noopener,noreferrer');
      }catch(error){
        alert(String(error.message||error));
      }finally{
        button.disabled=false; button.textContent=original;
      }
    }
    </script>'''
    page = page.replace("</body>", script + "</body>", 1)
    return HTMLResponse(page)
