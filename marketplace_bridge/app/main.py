from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import secrets as token_secrets
import time
from contextlib import asynccontextmanager
from urllib.parse import urlencode

import httpx
from fastapi import BackgroundTasks, FastAPI, Form, HTTPException
from fastapi.responses import HTMLResponse

from .db import Database
from .ebay import EbayClient
from .etsy import EtsyClient
from .security import SecretBox
from .settings import settings
from .shopify import ShopifyClient

logging.basicConfig(level=getattr(logging, __import__("os").getenv("BRIDGE_LOG_LEVEL", "INFO").upper(), logging.INFO))
log = logging.getLogger("marketplace_bridge")
db = Database(settings.database_path)
secrets = SecretBox.from_file(settings.data_dir / ".credential_key")


def get_credentials(provider: str) -> dict:
    encrypted = db.get_credential(provider)
    if not encrypted:
        raise HTTPException(400, f"{provider.title()} is not connected")
    return json.loads(secrets.decrypt(encrypted))


def save_credentials(provider: str, payload: dict):
    db.put_credential(provider, secrets.encrypt(json.dumps(payload)))


@asynccontextmanager
async def lifespan(app):
    log.info("Shop Sync ready; database=%s", settings.database_path)
    yield


app = FastAPI(title="Shop Sync", version="0.0.13", lifespan=lifespan)


@app.get("/health")
def health():
    return {"status": "ok", "version": app.version}


@app.get("/api/status")
def status():
    return {
        "ebay_connected": db.get_credential("ebay") is not None,
        "etsy_connected": db.get_credential("etsy") is not None,
        "shopify_connected": db.get_credential("shopify") is not None,
        "products": len(db.list_products()),
        "jobs": db.list_jobs(10),
    }


@app.post("/api/settings/ebay")
async def configure_ebay(access_token: str = Form(...)):
    client = EbayClient(access_token, settings.ebay_environment)
    await client.list_active_ids()  # Validates token before storage.
    save_credentials("ebay", {"access_token": access_token})
    return {"connected": True}


@app.post("/api/oauth/etsy/start")
async def start_etsy_oauth(
    keystring: str = Form(...),
    shared_secret: str = Form(...),
):
    verifier = token_secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    state = token_secrets.token_urlsafe(32)
    save_credentials("etsy_oauth", {
        "keystring": keystring.strip(),
        "shared_secret": shared_secret.strip(),
        "verifier": verifier,
        "state": state,
        "created_at": time.time(),
    })
    query = urlencode({
        "response_type": "code",
        "client_id": keystring.strip(),
        "redirect_uri": settings.etsy_redirect_uri,
        "scope": "listings_r shops_r",
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    })
    return {"authorization_url": f"https://www.etsy.com/oauth/connect?{query}"}


@app.post("/api/oauth/etsy/finish")
async def finish_etsy_oauth(oauth_result: str = Form(...)):
    pending = get_credentials("etsy_oauth")
    if time.time() - float(pending.get("created_at", 0)) > 900:
        db.delete_credential("etsy_oauth")
        raise HTTPException(400, "Etsy connection expired; start again")
    try:
        padded = oauth_result.strip() + "=" * (-len(oauth_result.strip()) % 4)
        result = json.loads(base64.urlsafe_b64decode(padded).decode())
    except Exception as exc:
        raise HTTPException(400, "Invalid Etsy authorization result") from exc
    if not token_secrets.compare_digest(str(result.get("state", "")), pending["state"]):
        raise HTTPException(400, "Etsy authorization state did not match")
    try:
        payload = await EtsyClient.exchange_code(
            pending["keystring"], result.get("code", ""), pending["verifier"], settings.etsy_redirect_uri
        )
        expires_at = time.time() + int(payload.get("expires_in", 3600))
        client = EtsyClient(
            pending["keystring"], pending["shared_secret"], "pending",
            payload["access_token"], payload.get("refresh_token", ""), expires_at,
        )
        shop = await client.find_authorised_shop()
    except httpx.HTTPStatusError as exc:
        log.warning("Etsy connection failed with HTTP status %s", exc.response.status_code)
        raise HTTPException(
            502,
            f"Etsy connection failed (HTTP {exc.response.status_code}); select Connect Etsy and try again",
        ) from exc
    except (KeyError, RuntimeError, ValueError) as exc:
        log.warning("Etsy connection failed: %s", exc)
        raise HTTPException(400, str(exc)) from exc
    client.shop_id = str(shop["shop_id"])
    save_credentials("etsy", client.credential_payload())
    db.delete_credential("etsy_oauth")
    return {"connected": True, "shop": shop.get("shop_name", client.shop_id)}


@app.post("/api/settings/shopify")
async def configure_shopify(shop_domain: str = Form(...), client_id: str = Form(...), client_secret: str = Form(...)):
    client = ShopifyClient(
        shop_domain,
        settings.shopify_api_version,
        client_id=client_id,
        client_secret=client_secret,
    )
    shop = await client.test()
    save_credentials("shopify", {
        "shop_domain": shop["myshopifyDomain"],
        "client_id": client_id,
        "client_secret": client_secret,
    })
    return {"connected": True, "shop": shop["name"]}


@app.post("/api/import/ebay")
def import_ebay(background_tasks: BackgroundTasks):
    get_credentials("ebay")
    job_id = db.create_job("ebay_import")
    background_tasks.add_task(run_ebay_import, job_id)
    return {"job_id": job_id}


@app.post("/api/import/etsy")
def import_etsy(background_tasks: BackgroundTasks):
    get_credentials("etsy")
    job_id = db.create_job("etsy_import")
    background_tasks.add_task(run_etsy_import, job_id)
    return {"job_id": job_id}


@app.post("/api/activity/clear")
def clear_activity():
    db.clear_finished_jobs()
    return {"cleared": True}


async def run_ebay_import(job_id: int):
    try:
        db.update_job(job_id, status="running", message="Reading active eBay listings")
        credential = get_credentials("ebay")
        client = EbayClient(credential["access_token"], settings.ebay_environment)
        ids = await client.list_active_ids()
        db.update_job(job_id, total=len(ids), message=f"Found {len(ids)} listings")
        for index, item_id in enumerate(ids, 1):
            product = await client.get_product(item_id)
            db.save_product(product)
            db.update_job(job_id, progress=index, message=f"Imported {product.title}")
        db.update_job(job_id, status="complete", message=f"Imported {len(ids)} listings")
    except Exception as exc:
        log.exception("eBay import failed")
        db.update_job(job_id, status="failed", message=str(exc)[:500])


async def run_etsy_import(job_id: int):
    try:
        db.update_job(job_id, status="running", message="Reading active Etsy listings")
        credential = get_credentials("etsy")
        client = EtsyClient(**credential)
        ids = await client.list_active_ids()
        save_credentials("etsy", client.credential_payload())
        db.update_job(job_id, total=len(ids), message=f"Found {len(ids)} listings")
        for index, listing_id in enumerate(ids, 1):
            product = await client.get_product(listing_id)
            db.save_product(product)
            save_credentials("etsy", client.credential_payload())
            db.update_job(job_id, progress=index, message=f"Imported {product.title}")
        db.update_job(job_id, status="complete", message=f"Imported {len(ids)} listings")
    except Exception as exc:
        log.exception("Etsy import failed")
        db.update_job(job_id, status="failed", message=str(exc)[:500])


@app.post("/api/products/{source}/{source_id}/shopify")
def export_shopify(source: str, source_id: str, background_tasks: BackgroundTasks):
    get_credentials("shopify")
    if not db.get_product(source, source_id):
        raise HTTPException(404, "Product not found")
    job_id = db.create_job("shopify_export")
    background_tasks.add_task(run_shopify_export, job_id, source, source_id)
    return {"job_id": job_id}


@app.post("/api/products/shopify/bulk")
def export_shopify_bulk(background_tasks: BackgroundTasks, selected: list[str] = Form(...)):
    if not selected:
        raise HTTPException(400, "Select at least one product")
    jobs = []
    for key in dict.fromkeys(selected):
        try:
            source, source_id = key.split(":", 1)
        except ValueError as exc:
            raise HTTPException(400, "Invalid product selection") from exc
        if not db.get_product(source, source_id):
            raise HTTPException(404, f"Product not found: {source} {source_id}")
        job_id = db.create_job("shopify_export")
        background_tasks.add_task(run_shopify_export, job_id, source, source_id)
        jobs.append(job_id)
    return {"job_ids": jobs, "count": len(jobs)}


async def run_shopify_export(job_id: int, source: str, source_id: str):
    try:
        db.update_job(job_id, status="running", total=1, message="Creating Shopify draft")
        product = db.get_product(source, source_id)
        credential = get_credentials("shopify")
        client = ShopifyClient(
            credential["shop_domain"],
            settings.shopify_api_version,
            client_id=credential["client_id"],
            client_secret=credential["client_secret"],
        )
        created = await client.create_draft(product)
        db.save_mapping(source, source_id, "shopify", created["id"], {"variants": created["variants"]["nodes"]})
        db.update_job(job_id, status="complete", progress=1, message=f"Created Shopify draft: {created['title']}")
    except Exception as exc:
        log.exception("Shopify export failed")
        db.update_job(job_id, status="failed", message=str(exc)[:500])


@app.get("/", response_class=HTMLResponse)
def dashboard():
    products = db.list_products()
    jobs = db.list_jobs()
    ebay_connected = db.get_credential("ebay") is not None
    etsy_connected = db.get_credential("etsy") is not None
    shopify_connected = db.get_credential("shopify") is not None
    return HTMLResponse(render_dashboard(products, jobs, ebay_connected, etsy_connected, shopify_connected))


def render_dashboard(products, jobs, ebay_connected, etsy_connected, shopify_connected):
    esc = __import__("html").escape
    product_rows = "".join(f'''<tr><td>{'' if p['shopify_id'] else f'<input class="product-select" type="checkbox" value="{esc(p["source"])}:{esc(p["source_id"])}" aria-label="Select {esc(p["title"])}">'} </td><td>{esc(p['title'])}<small>{esc(p['source'].title())} {esc(p['source_id'])}</small></td>
      <td><span class="pill {'ok' if p['shopify_id'] else ''}">{'Linked' if p['shopify_id'] else 'Imported'}</span></td>
      <td>{'' if p['shopify_id'] else f'<button onclick="send(\'api/products/{p["source"]}/{p["source_id"]}/shopify\')">Create Shopify draft</button>'}</td></tr>''' for p in products)
    job_rows = "".join(f"<tr><td>{esc(j['kind'].replace('_',' ').title())}</td><td>{esc(j['status'])}</td><td>{j['progress']}/{j['total']}</td><td>{esc(j['message'])}</td></tr>" for j in jobs)
    return f'''<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>Shop Sync</title>
    <style>
    :root{{--bg:#0b1220;--card:#121d2e;--line:#26364d;--text:#ecf4ff;--muted:#91a4bd;--blue:#36a3ff;--green:#29d391}}
    *{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--text);font:15px system-ui,sans-serif}}main{{max-width:1100px;margin:auto;padding:28px}}
    h1{{font-size:28px;margin:0}}h2{{font-size:18px;margin:0 0 16px}}p,small{{color:var(--muted)}}.hero{{display:flex;justify-content:space-between;align-items:center;margin-bottom:24px}}
    .grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:16px}}.card{{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:20px;margin-bottom:16px}}
    input{{width:100%;background:#09111e;color:var(--text);border:1px solid var(--line);padding:11px;border-radius:8px;margin:6px 0 12px}}input[type=checkbox]{{width:18px;height:18px;margin:0;accent-color:var(--blue)}}button,.button-link{{background:var(--blue);border:0;color:#04111e;font-weight:700;border-radius:8px;padding:10px 14px;cursor:pointer;text-decoration:none;display:inline-block}}
    .status{{display:flex;gap:8px;align-items:center}}.dot{{width:10px;height:10px;background:#e85d75;border-radius:50%}}.dot.ok{{background:var(--green)}}table{{width:100%;border-collapse:collapse}}td,th{{text-align:left;padding:12px;border-top:1px solid var(--line)}}small{{display:block;margin-top:3px}}.pill{{background:#2d3b50;padding:4px 8px;border-radius:99px;font-size:12px}}.pill.ok{{background:#145c47;color:#9effd8}}
    .footer{{text-align:center;color:var(--muted);font-size:12px;padding:10px 0 4px}}.footer a{{color:var(--muted)}}
    @media(max-width:650px){{main{{padding:16px}}.hero{{display:block}}table{{display:block;overflow:auto}}}}
    </style></head><body><main><div class="hero"><div><h1>Shop Sync</h1><p>Move complete listings between your marketplaces</p></div><a class="button-link" href="https://paypal.me/graffidoodle" target="_blank" rel="noopener noreferrer" aria-label="Buy me a beer">🍺 Buy me a beer</a></div>
    <div class="grid"><section class="card"><h2>eBay UK</h2><div class="status"><i class="dot {'ok' if ebay_connected else ''}"></i>{'Connected' if ebay_connected else 'Not connected'}</div>
    <form method="post" action="api/settings/ebay" onsubmit="connect(event)"><label>Production user access token</label><input name="access_token" type="password" required autocomplete="off"><button>Test and save</button></form></section>
    <section class="card"><h2>Etsy</h2><div class="status"><i class="dot {'ok' if etsy_connected else ''}"></i>{'Connected' if etsy_connected else 'Not connected'}</div>
    <form method="post" action="api/oauth/etsy/start" onsubmit="startEtsy(event)"><label>API keystring</label><input name="keystring" type="password" required autocomplete="off"><label>Shared secret</label><input name="shared_secret" type="password" required autocomplete="off"><button>Connect Etsy</button></form>
    <form method="post" action="api/oauth/etsy/finish" onsubmit="connect(event)" class="etsy-finish"><label>Authorization result</label><input name="oauth_result" required autocomplete="off" placeholder="Paste the result copied from the Etsy approval page"><button>Finish Etsy connection</button></form><small>Tokens and Shop ID are created automatically. Never paste them into chat or screenshots.</small></section>
    <section class="card"><h2>Shopify</h2><div class="status"><i class="dot {'ok' if shopify_connected else ''}"></i>{'Connected' if shopify_connected else 'Not connected'}</div>
    <form method="post" action="api/settings/shopify" onsubmit="connect(event)"><label>Store domain</label><input name="shop_domain" placeholder="store.myshopify.com" required><label>Client ID</label><input name="client_id" type="password" required autocomplete="off"><label>Client secret</label><input name="client_secret" type="password" required autocomplete="off"><button>Test and save</button></form></section></div>
    <section class="card"><h2>Import</h2><button onclick="send('api/import/ebay')" {'disabled' if not ebay_connected else ''}>Import eBay listings</button> <button onclick="send('api/import/etsy')" {'disabled' if not etsy_connected else ''}>Import Etsy listings</button></section>
    <section class="card"><div class="hero"><h2>Products</h2><div><button onclick="toggleAll()">Select all</button> <button onclick="createSelected()">Create selected drafts</button></div></div><table><thead><tr><th>Select</th><th>Listing</th><th>Status</th><th>Action</th></tr></thead><tbody>{product_rows or '<tr><td colspan="4">Connect a marketplace and import listings to begin.</td></tr>'}</tbody></table></section>
    <section class="card"><div class="hero"><h2>Activity</h2><button onclick="clearActivity()">Clear activity</button></div><table><thead><tr><th>Job</th><th>Status</th><th>Progress</th><th>Message</th></tr></thead><tbody>{job_rows or '<tr><td colspan="4">No activity yet.</td></tr>'}</tbody></table></section>
    <footer class="footer">Copyright © 2026 Adrian Apel · All rights reserved · <a href="https://github.com/Adya84/Marketplace-Shop-Sync-eBay-Etsy-Shopify/blob/main/LICENSE" target="_blank" rel="noopener noreferrer">Licence</a></footer>
    <script>
    function endpoint(path){{
      const base=location.pathname.endsWith('/')?location.pathname:location.pathname+'/';
      const action=path.startsWith('/')?path.slice(1):path;
      return base+action;
    }}
    async function connect(event){{
      event.preventDefault();
      const form=event.currentTarget;
      const button=form.querySelector('button');
      button.disabled=true; button.textContent='Testing...';
      try{{
        const response=await fetch(endpoint(form.getAttribute('action')),{{method:'POST',body:new FormData(form)}});
        if(!response.ok)throw new Error(await response.text());
        location.reload();
      }}catch(error){{alert(error.message); button.disabled=false; button.textContent='Test and save'}}
    }}
    async function startEtsy(event){{
      event.preventDefault();
      const form=event.currentTarget;
      const button=form.querySelector('button');
      button.disabled=true; button.textContent='Opening Etsy...';
      try{{
        const response=await fetch(endpoint(form.getAttribute('action')),{{method:'POST',body:new FormData(form)}});
        if(!response.ok)throw new Error(await response.text());
        const data=await response.json();
        window.open(data.authorization_url,'_blank','noopener');
        button.disabled=false; button.textContent='Connect Etsy';
      }}catch(error){{alert(error.message); button.disabled=false; button.textContent='Connect Etsy'}}
    }}
    async function send(path){{let r=await fetch(endpoint(path),{{method:'POST'}});if(!r.ok)alert(await r.text());else{{setTimeout(()=>location.reload(),800)}}}}
    function toggleAll(){{
      const boxes=[...document.querySelectorAll('.product-select')];
      const select=!boxes.every(box=>box.checked);
      boxes.forEach(box=>box.checked=select);
    }}
    async function createSelected(){{
      const selected=[...document.querySelectorAll('.product-select:checked')];
      if(!selected.length){{alert('Select at least one product');return}}
      if(!confirm(`Create ${{selected.length}} Shopify draft${{selected.length===1?'':'s'}}?`))return;
      const data=new FormData(); selected.forEach(box=>data.append('selected',box.value));
      const r=await fetch(endpoint('api/products/shopify/bulk'),{{method:'POST',body:data}});
      if(!r.ok)alert(await r.text());else location.reload();
    }}
    async function clearActivity(){{
      if(!confirm('Clear completed and failed activity?'))return;
      const r=await fetch(endpoint('api/activity/clear'),{{method:'POST'}});
      if(!r.ok)alert(await r.text());else location.reload();
    }}
    function formHasData(){{return [...document.querySelectorAll('input')].some(input => input.value.length > 0)}}
    setTimeout(()=>{{if(!formHasData())location.reload()}},10000)
    </script></main></body></html>'''
