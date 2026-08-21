from __future__ import annotations

import html
import secrets

from fastapi import APIRouter, BackgroundTasks, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select

from .catalog_service import EbayCloudClient, EtsyCloudClient, ShopifyCloudClient, create_job, get_product, list_products, save_mapping, save_product, update_job
from .config import get_settings
from .db import SessionLocal
from .marketplace_oauth import BrokerClient
from .models import MarketplaceConnection, Membership, SyncJob
from .security import decrypt_json, encrypt_json

router = APIRouter()
settings = get_settings()
broker = BrokerClient(settings.oauth_broker_url)

APP_LOGO = "https://raw.githubusercontent.com/Adya84/Marketplace-Shop-Sync-eBay-Etsy-Shopify/main/marketplace_bridge/logo.png"
LOGOS = {"shopify": "https://cdn.simpleicons.org/shopify/95BF47", "etsy": "https://cdn.simpleicons.org/etsy/F1641E", "ebay": "https://cdn.simpleicons.org/ebay/E53238"}
LABELS = {"shopify": "Shopify", "etsy": "Etsy", "ebay": "eBay"}


def esc(value) -> str:
    return html.escape(str(value or ""))


def workspace_id(request: Request) -> str:
    user_id = str(request.session.get("user_id") or "")
    wid = str(request.session.get("workspace_id") or "")
    if not user_id or not wid:
        raise HTTPException(401, "Sign in to Shop Sync")
    with SessionLocal() as db:
        membership = db.scalar(select(Membership).where(Membership.user_id == user_id, Membership.workspace_id == wid))
        if not membership:
            request.session.clear()
            raise HTTPException(401, "Sign in to Shop Sync")
    return wid


def verify_csrf(request: Request, value: str) -> None:
    expected = str(request.session.get("csrf") or "")
    if not expected or not secrets.compare_digest(expected, value):
        raise HTTPException(400, "Form expired. Refresh and try again.")


def credentials(wid: str, provider: str) -> dict:
    with SessionLocal() as db:
        row = db.scalar(select(MarketplaceConnection).where(MarketplaceConnection.workspace_id == wid, MarketplaceConnection.provider == provider))
        if not row or row.status != "connected" or not row.encrypted_credentials:
            raise HTTPException(400, f"{LABELS[provider]} is not connected")
        return decrypt_json(row.encrypted_credentials)


def save_credentials(wid: str, provider: str, payload: dict) -> None:
    with SessionLocal() as db:
        row = db.scalar(select(MarketplaceConnection).where(MarketplaceConnection.workspace_id == wid, MarketplaceConnection.provider == provider))
        if row:
            row.encrypted_credentials = encrypt_json(payload)
            db.commit()


async def run_import(job_id: str, wid: str, provider: str) -> None:
    try:
        update_job(job_id, status="running", progress="0/0", message=f"Reading {LABELS[provider]} catalogue")
        cred = credentials(wid, provider)
        if provider in {"etsy", "ebay"}:
            cred = await broker.ensure_fresh(provider, cred)
            save_credentials(wid, provider, cred)
        if provider == "shopify":
            client = ShopifyCloudClient(cred["shop_domain"], cred["access_token"])
            products = await client.list_products()
            total = len(products)
            update_job(job_id, progress=f"0/{total}", message=f"Found {total} Shopify products")
            for index, product in enumerate(products, 1):
                save_product(wid, product)
                update_job(job_id, progress=f"{index}/{total}", message=f"Imported {product['title']}")
        elif provider == "etsy":
            client = EtsyCloudClient(broker, cred)
            ids = await client.list_active_ids()
            total = len(ids)
            update_job(job_id, progress=f"0/{total}", message=f"Found {total} Etsy listings")
            for index, listing_id in enumerate(ids, 1):
                product = await client.get_product(listing_id)
                save_product(wid, product)
                update_job(job_id, progress=f"{index}/{total}", message=f"Imported {product['title']}")
        elif provider == "ebay":
            client = EbayCloudClient(cred["access_token"])
            ids = await client.list_active_ids()
            total = len(ids)
            update_job(job_id, progress=f"0/{total}", message=f"Found {total} eBay listings")
            for index, item_id in enumerate(ids, 1):
                product = await client.get_product(item_id)
                save_product(wid, product)
                update_job(job_id, progress=f"{index}/{total}", message=f"Imported {product['title']}")
        update_job(job_id, status="complete", message=f"{LABELS[provider]} import complete")
    except Exception as exc:
        update_job(job_id, status="failed", message=str(exc))


async def run_shopify_export(job_id: str, wid: str, source: str, source_id: str) -> None:
    try:
        update_job(job_id, status="running", progress="0/1", message="Creating Shopify draft")
        product = get_product(wid, source, source_id)
        if not product:
            raise RuntimeError("Product not found")
        cred = credentials(wid, "shopify")
        client = ShopifyCloudClient(cred["shop_domain"], cred["access_token"])
        created = await client.create_draft(product)
        destination_id = str(created.get("id") or "")
        save_mapping(wid, source, source_id, "shopify", destination_id, {"title": created.get("title")})
        update_job(job_id, status="complete", progress="1/1", message=f"Created Shopify draft: {created.get('title') or product['title']}")
    except Exception as exc:
        update_job(job_id, status="failed", message=str(exc))


@router.post("/sync/import/{provider}")
def import_provider(provider: str, request: Request, background_tasks: BackgroundTasks, csrf_token: str = Form(...)):
    verify_csrf(request, csrf_token)
    wid = workspace_id(request)
    if provider not in LABELS:
        raise HTTPException(404)
    credentials(wid, provider)
    job_id = create_job(wid, f"{provider}_import")
    background_tasks.add_task(run_import, job_id, wid, provider)
    return RedirectResponse("/catalog", status_code=303)


@router.post("/sync/export/shopify/{source}/{source_id}")
def export_shopify(source: str, source_id: str, request: Request, background_tasks: BackgroundTasks, csrf_token: str = Form(...)):
    verify_csrf(request, csrf_token)
    wid = workspace_id(request)
    credentials(wid, "shopify")
    if not get_product(wid, source, source_id):
        raise HTTPException(404, "Product not found")
    job_id = create_job(wid, "shopify_export")
    background_tasks.add_task(run_shopify_export, job_id, wid, source, source_id)
    return RedirectResponse("/catalog", status_code=303)


@router.post("/sync/activity/clear")
def clear_activity(request: Request, csrf_token: str = Form(...)):
    verify_csrf(request, csrf_token)
    wid = workspace_id(request)
    with SessionLocal() as db:
        for row in db.scalars(select(SyncJob).where(SyncJob.workspace_id == wid, SyncJob.status.in_(["complete", "failed"]))).all():
            db.delete(row)
        db.commit()
    return RedirectResponse("/catalog", status_code=303)


def page_shell(body: str) -> HTMLResponse:
    return HTMLResponse(f'''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Catalogue · Shop Sync</title><style>:root{{--bg:#06101c;--card:#0d1c2e;--line:#22364f;--text:#f5f8fc;--muted:#8fa6c2;--blue:#5cc0ff;--green:#38d4a0}}*{{box-sizing:border-box}}body{{margin:0;background:radial-gradient(circle at 15% 0,#12345c 0,transparent 30%),var(--bg);color:var(--text);font:14px system-ui,sans-serif}}main{{max-width:1280px;margin:auto;padding:24px}}a{{color:var(--blue)}}.top{{display:flex;justify-content:space-between;align-items:center;gap:14px;margin-bottom:18px}}.brand{{display:flex;gap:12px;align-items:center}}.brand img{{width:55px;height:55px;object-fit:contain;border-radius:14px}}h1{{margin:0;font-size:28px}}h2{{margin:0 0 12px}}.muted{{color:var(--muted)}}.card{{background:linear-gradient(180deg,#112237,#091827);border:1px solid var(--line);border-radius:18px;padding:18px;margin-bottom:16px}}.actions{{display:flex;gap:9px;flex-wrap:wrap}}button,.btn{{border:0;border-radius:9px;background:var(--blue);color:#05111d;font-weight:800;padding:9px 12px;text-decoration:none;cursor:pointer}}.secondary{{background:#172b42!important;color:var(--text)!important;border:1px solid var(--line)!important}}.market-logo{{width:22px;height:22px;vertical-align:middle;background:white;border-radius:6px;padding:3px;margin-right:5px}}table{{width:100%;border-collapse:collapse}}th,td{{padding:10px;border-top:1px solid var(--line);text-align:left;vertical-align:top}}th{{color:#9bb0c7}}small{{display:block;color:var(--muted);margin-top:3px}}.pill{{display:inline-block;padding:4px 7px;border-radius:99px;background:#16314a;color:#cbe4fa;font-size:11px}}.ok{{background:#104d3d;color:#b8ffe6}}@media(max-width:760px){{main{{padding:14px}}table{{display:block;overflow:auto}}.top{{align-items:flex-start;flex-direction:column}}}}</style></head><body><main>{body}</main></body></html>''')


@router.get("/catalog", response_class=HTMLResponse)
def catalog(request: Request):
    wid = workspace_id(request)
    token = str(request.session.get("csrf") or "")
    with SessionLocal() as db:
        connections = {row.provider: row for row in db.scalars(select(MarketplaceConnection).where(MarketplaceConnection.workspace_id == wid)).all()}
        jobs = db.scalars(select(SyncJob).where(SyncJob.workspace_id == wid).order_by(SyncJob.created_at.desc()).limit(15)).all()
    import_buttons = []
    for provider in ("shopify", "etsy", "ebay"):
        row = connections.get(provider)
        if row and row.status == "connected":
            import_buttons.append(f'''<form method="post" action="/sync/import/{provider}"><input type="hidden" name="csrf_token" value="{esc(token)}"><button><img class="market-logo" src="{LOGOS[provider]}" alt="">Import {LABELS[provider]}</button></form>''')
    products = list_products(wid)
    rows = []
    for product in products:
        source = str(product.get("source") or "")
        source_id = str(product.get("source_id") or "")
        mapped = product.get("mappings") or {}
        actions = []
        if source != "shopify" and connections.get("shopify") and connections["shopify"].status == "connected":
            if mapped.get("shopify"):
                actions.append('<span class="pill ok">Sent to Shopify</span>')
            else:
                actions.append(f'''<form method="post" action="/sync/export/shopify/{esc(source)}/{esc(source_id)}"><input type="hidden" name="csrf_token" value="{esc(token)}"><button>Create Shopify draft</button></form>''')
        if source == "shopify":
            if connections.get("etsy") and connections["etsy"].status == "connected": actions.append('<span class="pill">Etsy export mapping next</span>')
            if connections.get("ebay") and connections["ebay"].status == "connected": actions.append('<span class="pill">eBay export mapping next</span>')
        image = ((product.get("images") or [{}])[0]).get("url") or ""
        thumb = f'<img src="{esc(image)}" alt="" style="width:52px;height:52px;object-fit:cover;border-radius:8px">' if image else ''
        rows.append(f'''<tr><td>{thumb}</td><td><strong>{esc(product.get('title'))}</strong><small>{esc(source.title())} · {esc(source_id)}</small></td><td>{esc(product.get('sku_summary')) or '—'}<small>{int(product.get('variant_count') or 0)} variants</small></td><td>{int(product.get('stock_total') or 0)}</td><td><div class="actions">{''.join(actions) or '<span class="muted">No action</span>'}</div></td></tr>''')
    job_rows = ''.join(f'''<tr><td>{esc(j.kind.replace('_',' ').title())}</td><td>{esc(j.status)}</td><td>{esc(j.progress)}</td><td>{esc(j.message)}</td></tr>''' for j in jobs) or '<tr><td colspan="4" class="muted">No jobs yet.</td></tr>'
    return page_shell(f'''<div class="top"><div class="brand"><img src="{APP_LOGO}" alt="Shop Sync logo"><div><h1>Product workspace</h1><div class="muted">Import, review and move complete listings between marketplaces.</div></div></div><a class="btn secondary" href="/dashboard">← Dashboard</a></div><section class="card"><h2>Import catalogues</h2><div class="actions">{''.join(import_buttons) or '<span class="muted">Connect a marketplace first.</span>'}</div></section><section class="card"><h2>Catalogue</h2><table><thead><tr><th></th><th>Product</th><th>SKU / variants</th><th>Qty</th><th>Actions</th></tr></thead><tbody>{''.join(rows) or '<tr><td colspan="5" class="muted">Import a marketplace to load products.</td></tr>'}</tbody></table></section><section class="card"><div class="top" style="margin:0"><h2>Activity</h2><form method="post" action="/sync/activity/clear"><input type="hidden" name="csrf_token" value="{esc(token)}"><button class="secondary">Clear finished</button></form></div><table><thead><tr><th>Job</th><th>Status</th><th>Progress</th><th>Message</th></tr></thead><tbody>{job_rows}</tbody></table></section>''')
