from __future__ import annotations

import html
import json
import re
import secrets

import httpx
from fastapi import APIRouter, BackgroundTasks, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select

from .catalog_service import (
    EbayCloudClient,
    EtsyCloudClient,
    ShopifyCloudClient,
    create_job,
    get_product,
    list_products,
    save_mapping,
    save_product,
    update_job,
)
from .config import get_settings
from .db import SessionLocal
from .marketplace_oauth import BrokerClient
from .models import ListingMapping, MarketplaceConnection, Membership, SyncJob, WorkspaceSetting
from .reverse_sync import EbayDraftWriter, EtsyDraftWriter, build_plan
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


def get_setting(wid: str, key: str) -> dict:
    with SessionLocal() as db:
        row = db.scalar(select(WorkspaceSetting).where(WorkspaceSetting.workspace_id == wid, WorkspaceSetting.key == key))
        if not row:
            return {}
        try:
            return json.loads(row.value or "{}")
        except Exception:
            return {}


def save_setting(wid: str, key: str, value: dict) -> None:
    with SessionLocal() as db:
        row = db.scalar(select(WorkspaceSetting).where(WorkspaceSetting.workspace_id == wid, WorkspaceSetting.key == key))
        if not row:
            row = WorkspaceSetting(workspace_id=wid, key=key)
            db.add(row)
        row.value = json.dumps(value, separators=(",", ":"))
        db.commit()


def mapped_id(wid: str, source_id: str, destination: str) -> str:
    with SessionLocal() as db:
        row = db.scalar(select(ListingMapping).where(ListingMapping.workspace_id == wid, ListingMapping.source == "shopify", ListingMapping.source_id == source_id, ListingMapping.destination == destination))
        return str(row.destination_id) if row else ""


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


class CloudEtsyWriterClient:
    def __init__(self, wid: str, cred: dict):
        self.wid = wid
        self.credentials = cred
        self.shop_id = str(cred.get("shop_id") or "")
        if not self.shop_id:
            raise ValueError("Etsy shop ID is missing; reconnect Etsy")

    async def request(self, method: str, path: str, *, params=None, form=None, json_data=None):
        fresh = await broker.ensure_fresh("etsy", self.credentials)
        if fresh != self.credentials:
            self.credentials = fresh
            save_credentials(self.wid, "etsy", fresh)
        return await broker.etsy_request(self.credentials, method, path, params=params, form=form, json_data=json_data)


def ebay_xml(value) -> str:
    return html.escape(str(value or ""), quote=False)


async def revise_ebay_existing(access_token: str, item_id: str, listing: dict) -> dict:
    variants = listing.get("variants") or []
    if not variants:
        raise ValueError("Shopify product has no variants")
    pictures = "".join(f"<PictureURL>{ebay_xml(i.get('url'))}</PictureURL>" for i in listing.get("images") or [] if i.get("url"))
    if len(variants) > 1:
        names = listing.get("kept_options") or []
        specifics_set = "".join(
            "<NameValueList><Name>%s</Name><Value>%s</Value></NameValueList>" % (ebay_xml(name), ebay_xml(value))
            for name in names
            for value in dict.fromkeys(next((o.get("value") for o in v.get("options") or [] if o.get("name") == name), "") for v in variants)
            if value
        )
        variation_rows = []
        for variant in variants:
            specs = "".join(f"<NameValueList><Name>{ebay_xml(o.get('name'))}</Name><Value>{ebay_xml(o.get('value'))}</Value></NameValueList>" for o in variant.get("options") or [] if o.get("name") != "Title")
            variation_rows.append(f"<Variation><SKU>{ebay_xml(variant.get('sku'))}</SKU><StartPrice>{ebay_xml(variant.get('price'))}</StartPrice><Quantity>{max(0,int(variant.get('quantity') or 0))}</Quantity><VariationSpecifics>{specs}</VariationSpecifics></Variation>")
        variant_xml = f"<Variations>{''.join(variation_rows)}<VariationSpecificsSet>{specifics_set}</VariationSpecificsSet></Variations>"
    else:
        variant = variants[0]
        variant_xml = f"<SKU>{ebay_xml(variant.get('sku'))}</SKU><StartPrice>{ebay_xml(variant.get('price'))}</StartPrice><Quantity>{max(0,int(variant.get('quantity') or 0))}</Quantity>"
    body = f'''<?xml version="1.0" encoding="utf-8"?><ReviseFixedPriceItemRequest xmlns="urn:ebay:apis:eBLBaseComponents"><Item><ItemID>{ebay_xml(item_id)}</ItemID><Title>{ebay_xml(listing['title'][:80])}</Title><Description>{ebay_xml(listing.get('description_html') or listing['title'])}</Description><PictureDetails>{pictures}</PictureDetails>{variant_xml}</Item></ReviseFixedPriceItemRequest>'''
    headers = {"X-EBAY-API-CALL-NAME": "ReviseFixedPriceItem", "X-EBAY-API-COMPATIBILITY-LEVEL": "1423", "X-EBAY-API-SITEID": "3", "X-EBAY-API-IAF-TOKEN": access_token, "Content-Type": "text/xml"}
    async with httpx.AsyncClient(timeout=90) as client:
        response = await client.post("https://api.ebay.com/ws/api.dll", content=body.encode(), headers=headers)
        response.raise_for_status()
    if "<Ack>Failure</Ack>" in response.text:
        match = re.search(r"<LongMessage>(.*?)</LongMessage>", response.text, re.S)
        raise RuntimeError(html.unescape(match.group(1)) if match else "eBay rejected the listing update")
    return {"item_id": item_id, "updated": True}


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


@router.post("/sync/defaults/{destination}")
def reverse_defaults(destination: str, request: Request, csrf_token: str = Form(...), payload: str = Form(...)):
    verify_csrf(request, csrf_token)
    wid = workspace_id(request)
    if destination not in {"etsy", "ebay"}:
        raise HTTPException(400, "Destination must be Etsy or eBay")
    try:
        values = json.loads(payload or "{}")
        if not isinstance(values, dict):
            raise ValueError
    except Exception as exc:
        raise HTTPException(400, "Defaults must be valid JSON") from exc
    save_setting(wid, f"reverse_{destination}_defaults", values)
    return RedirectResponse("/catalog", status_code=303)


@router.get("/sync/reverse/{source_id}/{destination}", response_class=HTMLResponse)
def reverse_review(source_id: str, destination: str, request: Request):
    wid = workspace_id(request)
    if destination not in {"etsy", "ebay"}:
        raise HTTPException(404)
    credentials(wid, destination)
    product = get_product(wid, "shopify", source_id)
    if not product:
        raise HTTPException(404, "Shopify product not found; import Shopify first")
    defaults = get_setting(wid, f"reverse_{destination}_defaults")
    plan = build_plan(product, destination, defaults, list_products(wid), mapped_id(wid, source_id, destination))
    token = str(request.session.get("csrf") or "")
    if plan["missing_defaults"]:
        return page_shell(f'''<div class="top"><div class="brand"><img src="{APP_LOGO}" alt="Shop Sync logo"><div><h1>{LABELS[destination]} export setup</h1><div class="muted">{esc(product.get('title'))}</div></div></div><a class="btn secondary" href="/catalog">← Product workspace</a></div><section class="card"><h2>Marketplace defaults needed</h2><p>Before Shop Sync can create a {LABELS[destination]} draft, save: <strong>{esc(', '.join(plan['missing_defaults']))}</strong>.</p><p class="muted">Return to Product workspace → Marketplace export defaults and enter the required IDs once.</p></section>''')
    sections = []
    for index, listing in enumerate(plan["listings"]):
        candidates = listing.get("existing_candidates") or []
        candidate_html = ""
        if candidates:
            candidate_rows = []
            for candidate in candidates[:8]:
                candidate_rows.append(f'''<label class="candidate"><input type="radio" name="existing_id" value="{esc(candidate['source_id'])}"><span><strong>{esc(candidate.get('title') or candidate['source_id'])}</strong><small>{esc(candidate['reason'])} · score {int(candidate['score'])}</small></span></label>''')
            candidate_html = f'''<div class="match-box"><h3>Possible existing listing found</h3><p>Choose one to overwrite/update, or choose Create new below.</p>{''.join(candidate_rows)}</div>'''
        split_note = f'''<div class="notice">Etsy has a two-variation-property limit. Shop Sync split this Shopify product into {plan['listing_count']} drafts.</div>''' if plan["split_for_etsy"] else ""
        sections.append(f'''<section class="card">{split_note}<div class="top" style="margin:0"><div><h2>{esc(listing['title'])}</h2><p>{len(listing.get('variants') or [])} variants · quantity {sum(max(0,int(v.get('quantity') or 0)) for v in listing.get('variants') or [])}</p></div><img class="market-logo big" src="{LOGOS[destination]}" alt=""></div><form method="post" action="/sync/reverse/{source_id}/{destination}/export"><input type="hidden" name="csrf_token" value="{esc(token)}"><input type="hidden" name="listing_index" value="{index}">{candidate_html}<label class="candidate"><input type="radio" name="create_new" value="true" {'checked' if not candidates else ''}><span><strong>Create new {LABELS[destination]} draft</strong><small>Do not overwrite an existing listing.</small></span></label><button style="margin-top:14px">Continue with this choice</button></form></section>''')
    return page_shell(f'''<div class="top"><div class="brand"><img src="{APP_LOGO}" alt="Shop Sync logo"><div><h1>Review {LABELS[destination]} export</h1><div class="muted">Shopify → {LABELS[destination]} · duplicate check by mapping, SKU, title and photos</div></div></div><a class="btn secondary" href="/catalog">← Product workspace</a></div>{''.join(sections)}''')


@router.post("/sync/reverse/{source_id}/{destination}/export")
async def reverse_export(source_id: str, destination: str, request: Request, csrf_token: str = Form(...), listing_index: int = Form(0), existing_id: str = Form(""), create_new: str = Form("")):
    verify_csrf(request, csrf_token)
    wid = workspace_id(request)
    if destination not in {"etsy", "ebay"}:
        raise HTTPException(404)
    product = get_product(wid, "shopify", source_id)
    if not product:
        raise HTTPException(404, "Shopify product not found")
    defaults = get_setting(wid, f"reverse_{destination}_defaults")
    plan = build_plan(product, destination, defaults, list_products(wid), mapped_id(wid, source_id, destination))
    if plan["missing_defaults"]:
        raise HTTPException(400, "Missing marketplace defaults: " + ", ".join(plan["missing_defaults"]))
    if listing_index < 0 or listing_index >= len(plan["listings"]):
        raise HTTPException(400, "Invalid generated listing")
    listing = plan["listings"][listing_index]
    candidates = listing.get("existing_candidates") or []
    create = str(create_new).lower() == "true"
    if candidates and not existing_id and not create:
        raise HTTPException(409, "Existing listing match found. Choose Update existing or Create new.")
    job_id = create_job(wid, f"{destination}_export")
    update_job(job_id, status="running", progress="0/1", message=f"Preparing {LABELS[destination]} draft")
    try:
        cred = credentials(wid, destination)
        cred = await broker.ensure_fresh(destination, cred)
        save_credentials(wid, destination, cred)
        if destination == "etsy":
            client = CloudEtsyWriterClient(wid, cred)
            result = await EtsyDraftWriter(client).create_or_update(listing, defaults, existing_id)
            destination_id = str(result.get("listing_id") or existing_id)
        else:
            if existing_id:
                result = await revise_ebay_existing(cred["access_token"], existing_id, listing)
                destination_id = existing_id
            else:
                result = await EbayDraftWriter(cred["access_token"], str(defaults.get("marketplace_id") or "EBAY_GB")).create_draft(listing, defaults)
                destination_id = str(result.get("group_key") or ((result.get("offer_ids") or [""])[0]))
        save_mapping(wid, "shopify", source_id, destination, destination_id, {"listing_index": listing_index, "result": result})
        update_job(job_id, status="complete", progress="1/1", message=f"{LABELS[destination]} {'listing updated' if existing_id else 'draft created'}")
    except Exception as exc:
        update_job(job_id, status="failed", message=str(exc))
        raise HTTPException(400, str(exc)) from exc
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
    return HTMLResponse(f'''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Shop Sync</title><style>:root{{--bg:#06101c;--card:#0d1c2e;--line:#22364f;--text:#f5f8fc;--muted:#8fa6c2;--blue:#5cc0ff;--green:#38d4a0}}*{{box-sizing:border-box}}body{{margin:0;background:radial-gradient(circle at 15% 0,#12345c 0,transparent 30%),var(--bg);color:var(--text);font:14px system-ui,sans-serif}}main{{max-width:1280px;margin:auto;padding:24px}}a{{color:var(--blue)}}.top{{display:flex;justify-content:space-between;align-items:center;gap:14px;margin-bottom:18px}}.brand{{display:flex;gap:12px;align-items:center}}.brand img{{width:55px;height:55px;object-fit:contain;border-radius:14px}}h1{{margin:0;font-size:28px}}h2{{margin:0 0 12px}}h3{{margin:8px 0}}p{{color:var(--muted);line-height:1.5}}.muted{{color:var(--muted)}}.card{{background:linear-gradient(180deg,#112237,#091827);border:1px solid var(--line);border-radius:18px;padding:18px;margin-bottom:16px}}.actions{{display:flex;gap:9px;flex-wrap:wrap}}button,.btn{{border:0;border-radius:9px;background:var(--blue);color:#05111d;font-weight:800;padding:9px 12px;text-decoration:none;cursor:pointer}}.secondary{{background:#172b42!important;color:var(--text)!important;border:1px solid var(--line)!important}}.market-logo{{width:22px;height:22px;vertical-align:middle;background:white;border-radius:6px;padding:3px;margin-right:5px}}.market-logo.big{{width:48px;height:48px;padding:7px}}table{{width:100%;border-collapse:collapse}}th,td{{padding:10px;border-top:1px solid var(--line);text-align:left;vertical-align:top}}th{{color:#9bb0c7}}small{{display:block;color:var(--muted);margin-top:3px}}.pill{{display:inline-block;padding:4px 7px;border-radius:99px;background:#16314a;color:#cbe4fa;font-size:11px}}.ok{{background:#104d3d;color:#b8ffe6}}textarea{{width:100%;min-height:120px;background:#071521;color:var(--text);border:1px solid var(--line);border-radius:9px;padding:10px}}.candidate{{display:flex;gap:10px;align-items:flex-start;padding:10px;background:#071521;border:1px solid var(--line);border-radius:10px;margin:7px 0}}.candidate input{{margin-top:4px}}.match-box{{padding:10px;border:1px solid #72572a;background:#2c2416;border-radius:10px;margin:12px 0}}.notice{{padding:10px;border-radius:10px;background:#12314a;color:#cbe9ff;margin-bottom:12px}}@media(max-width:760px){{main{{padding:14px}}table{{display:block;overflow:auto}}.top{{align-items:flex-start;flex-direction:column}}}}</style></head><body><main>{body}</main></body></html>''')


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
                actions.append(f'''<form method="post" action="/sync/export/shopify/{esc(source)}/{esc(source_id)}"><input type="hidden" name="csrf_token" value="{esc(token)}"><button><img class="market-logo" src="{LOGOS['shopify']}" alt="">Create Shopify draft</button></form>''')
        if source == "shopify":
            for destination in ("etsy", "ebay"):
                if connections.get(destination) and connections[destination].status == "connected":
                    label = "Review/update " + LABELS[destination] if mapped.get(destination) else "Export draft to " + LABELS[destination]
                    actions.append(f'''<a class="btn" href="/sync/reverse/{esc(source_id)}/{destination}"><img class="market-logo" src="{LOGOS[destination]}" alt="">{esc(label)}</a>''')
        image = ((product.get("images") or [{}])[0]).get("url") or ""
        thumb = f'<img src="{esc(image)}" alt="" style="width:52px;height:52px;object-fit:cover;border-radius:8px">' if image else ''
        rows.append(f'''<tr><td>{thumb}</td><td><strong>{esc(product.get('title'))}</strong><small>{esc(source.title())} · {esc(source_id)}</small></td><td>{esc(product.get('sku_summary')) or '—'}<small>{int(product.get('variant_count') or 0)} variants</small></td><td>{int(product.get('stock_total') or 0)}</td><td><div class="actions">{''.join(actions) or '<span class="muted">No action</span>'}</div></td></tr>''')
    job_rows = ''.join(f'''<tr><td>{esc(j.kind.replace('_',' ').title())}</td><td>{esc(j.status)}</td><td>{esc(j.progress)}</td><td>{esc(j.message)}</td></tr>''' for j in jobs) or '<tr><td colspan="4" class="muted">No jobs yet.</td></tr>'
    etsy_defaults = esc(json.dumps(get_setting(wid, "reverse_etsy_defaults"), indent=2))
    ebay_defaults = esc(json.dumps(get_setting(wid, "reverse_ebay_defaults"), indent=2))
    return page_shell(f'''<div class="top"><div class="brand"><img src="{APP_LOGO}" alt="Shop Sync logo"><div><h1>Product workspace</h1><div class="muted">Import, review and move complete listings between marketplaces.</div></div></div><a class="btn secondary" href="/dashboard">← Dashboard</a></div><section class="card"><h2>Import catalogues</h2><div class="actions">{''.join(import_buttons) or '<span class="muted">Connect a marketplace first.</span>'}</div></section><section class="card"><h2>Catalogue</h2><table><thead><tr><th></th><th>Product</th><th>SKU / variants</th><th>Qty</th><th>Actions</th></tr></thead><tbody>{''.join(rows) or '<tr><td colspan="5" class="muted">Import a marketplace to load products.</td></tr>'}</tbody></table></section><section class="card"><details><summary><strong>Marketplace export defaults</strong></summary><p>Save marketplace-required IDs once. Shop Sync only uses these where Shopify has no equivalent field.</p><div class="top" style="align-items:flex-start"><form method="post" action="/sync/defaults/etsy" style="flex:1"><input type="hidden" name="csrf_token" value="{esc(token)}"><h3>Etsy</h3><textarea name="payload" placeholder='{{"taxonomy_id":"...","shipping_profile_id":"...","readiness_state_id":"..."}}'>{etsy_defaults}</textarea><button>Save Etsy defaults</button></form><form method="post" action="/sync/defaults/ebay" style="flex:1"><input type="hidden" name="csrf_token" value="{esc(token)}"><h3>eBay</h3><textarea name="payload" placeholder='{{"category_id":"...","merchant_location_key":"...","payment_policy_id":"...","return_policy_id":"...","fulfillment_policy_id":"..."}}'>{ebay_defaults}</textarea><button>Save eBay defaults</button></form></div></details></section><section class="card"><div class="top" style="margin:0"><h2>Activity</h2><form method="post" action="/sync/activity/clear"><input type="hidden" name="csrf_token" value="{esc(token)}"><button class="secondary">Clear finished</button></form></div><table><thead><tr><th>Job</th><th>Status</th><th>Progress</th><th>Message</th></tr></thead><tbody>{job_rows}</tbody></table></section>''')
