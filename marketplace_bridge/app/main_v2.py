from __future__ import annotations

import html
import secrets as token_secrets
import time

import httpx
from fastapi import Form, HTTPException

from . import main as legacy
from .ebay import EbayClient, EbayListingUnavailable
from .ebay_broker import EbayOAuthBroker, parse_authorization_result
from .settings import settings

app = legacy.app
app.version = "0.0.26"
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


def _catalogue_section(products: list[dict]) -> str:
    esc = html.escape
    pending = [
        p for p in products
        if p["source"] != "shopify"
        and not p["shopify_id"]
        and (not p.get("is_duplicate", False) or p.get("duplicate_approved_shopify", False))
    ]
    rows = []
    for p in pending:
        source = str(p.get("source") or "")
        source_id = str(p.get("source_id") or "")
        title = str(p.get("title") or "")
        skus = p.get("skus") or []
        sku_summary = str(p.get("sku_summary") or "")
        stock = int(p.get("stock_total") or 0)
        variants = int(p.get("variant_count") or 0)
        search_value = " ".join([title, source, source_id, *[str(s) for s in skus]]).casefold()
        variant_note = f"{variants} variant{'s' if variants != 1 else ''}" if variants else "No variants"
        rows.append(
            f'''<tr class="catalogue-row" data-source="{esc(source)}" data-search="{esc(search_value, quote=True)}">
            <td><input class="product-select" type="checkbox" value="{esc(source)}:{esc(source_id)}" aria-label="Select {esc(title)}"></td>
            <td>{esc(title)}<small>{esc(source.title())} {esc(source_id)}</small></td>
            <td>{esc(sku_summary) if sku_summary else '<span class="muted-dash">—</span>'}<small>{esc(variant_note)}</small></td>
            <td><strong>{stock}</strong></td>
            <td><span class="pill">Imported</span></td>
            <td><button onclick="send('api/products/{esc(source)}/{esc(source_id)}/shopify')">Create Shopify draft</button></td>
            </tr>'''
        )
    body = "".join(rows) or '<tr><td colspan="6">No listings waiting to be sent.</td></tr>'
    return f'''<section class="card" id="catalogue-card">
      <div class="hero catalogue-heading"><div><h2>Ready to send</h2><p id="catalogue-count">{len(pending)} listing{'s' if len(pending) != 1 else ''} ready</p></div>
      <div><button onclick="toggleAll()">Select page</button> <button onclick="createSelected()">Create selected drafts</button></div></div>
      <div class="catalogue-tools">
        <label>Search<input id="catalogue-search" type="search" placeholder="Title, SKU or listing ID" autocomplete="off"></label>
        <label>Marketplace<select id="catalogue-source"><option value="all">All marketplaces</option><option value="ebay">eBay</option><option value="etsy">Etsy</option><option value="shopify">Shopify</option><option value="tiktok">TikTok</option></select></label>
      </div>
      <div class="table-wrap"><table><thead><tr><th>Select</th><th>Listing</th><th>SKU / variants</th><th>Stock</th><th>Status</th><th>Action</th></tr></thead><tbody id="catalogue-body">{body}</tbody></table></div>
      <div class="catalogue-footer"><span id="catalogue-range"></span><div id="catalogue-pages" class="catalogue-pages"></div></div>
    </section>'''


def render_dashboard(*args, **kwargs):
    page = _original_render_dashboard(*args, **kwargs)
    products = args[0] if args else kwargs.get("products", [])

    old = '''<form method="post" action="api/oauth/ebay/start" onsubmit="startEbay(event)"><label>App ID (Client ID)</label><input name="client_id" type="password" required autocomplete="off"><label>Cert ID (Client secret)</label><input name="client_secret" type="password" required autocomplete="off"><label>RuName (eBay Redirect URL name)</label><input name="runame" type="password" required autocomplete="off"><button>Connect eBay</button></form>
    <form method="post" action="api/oauth/ebay/finish" onsubmit="connect(event)"><label>eBay callback URL</label><input name="oauth_result" required autocomplete="off" placeholder="Paste the full callback URL after approving eBay"><button>Finish eBay connection</button></form><small>Shop Sync stores the refresh token encrypted and renews the short-lived eBay access token automatically. Keep the Cert ID and tokens private.</small>'''
    new = '''<form method="post" action="api/oauth/ebay/start" onsubmit="startEbay(event)"><button>Connect eBay</button></form>
    <form method="post" action="api/oauth/ebay/finish" onsubmit="connect(event)"><label>Authorization result</label><input name="oauth_result" required autocomplete="off" placeholder="Paste the result copied after eBay approval"><button>Finish eBay connection</button></form><small>No eBay developer account is required. Sign in to your seller account, approve Shop Sync, copy the authorization result, and paste it here. Tokens are stored locally and refreshed automatically.</small>'''
    page = page.replace(old, new)

    ready_start = '<section class="card"><div class="hero"><h2>Ready to send</h2>'
    completed_start = '<section class="card"><div class="hero"><h2>Completed</h2>'
    start = page.find(ready_start)
    end = page.find(completed_start)
    if start != -1 and end != -1 and end > start:
        page = page[:start] + _catalogue_section(products) + page[end:]

    extra_css = '''
    .catalogue-tools{display:grid;grid-template-columns:minmax(220px,1fr) minmax(160px,240px);gap:12px;margin:8px 0 16px}.catalogue-tools label{color:var(--muted);font-size:13px}.catalogue-tools input,.catalogue-tools select{width:100%;background:#09111e;color:var(--text);border:1px solid var(--line);padding:11px;border-radius:8px;margin:6px 0 0}.table-wrap{overflow:auto}.catalogue-footer{display:flex;justify-content:space-between;align-items:center;gap:12px;margin-top:14px;color:var(--muted)}.catalogue-pages{display:flex;flex-wrap:wrap;gap:6px;justify-content:flex-end}.catalogue-pages button{padding:7px 10px;min-width:36px}.catalogue-pages button.active{background:var(--green)}.catalogue-pages button:disabled{opacity:.45;cursor:not-allowed}.muted-dash{color:var(--muted)}.catalogue-heading p{margin:4px 0 0}
    @media(max-width:650px){.catalogue-tools{grid-template-columns:1fr}.catalogue-footer{align-items:flex-start;flex-direction:column}.catalogue-pages{justify-content:flex-start}}
    '''
    page = page.replace('</style>', extra_css + '</style>')

    extra_js = '''
    const cataloguePageSize=50;
    let cataloguePage=1;
    function catalogueFilteredRows(){
      const query=(document.getElementById('catalogue-search')?.value||'').trim().toLowerCase();
      const source=document.getElementById('catalogue-source')?.value||'all';
      return [...document.querySelectorAll('#catalogue-body .catalogue-row')].filter(row=>{
        const sourceMatch=source==='all'||row.dataset.source===source;
        const searchMatch=!query||(row.dataset.search||'').includes(query);
        return sourceMatch&&searchMatch;
      });
    }
    function renderCatalogue(){
      const all=[...document.querySelectorAll('#catalogue-body .catalogue-row')];
      if(!all.length)return;
      const filtered=catalogueFilteredRows();
      const pages=Math.max(1,Math.ceil(filtered.length/cataloguePageSize));
      cataloguePage=Math.min(Math.max(1,cataloguePage),pages);
      all.forEach(row=>row.hidden=true);
      const start=(cataloguePage-1)*cataloguePageSize;
      const visible=filtered.slice(start,start+cataloguePageSize);
      visible.forEach(row=>row.hidden=false);
      const range=document.getElementById('catalogue-range');
      if(range)range.textContent=filtered.length?`Showing ${start+1}–${start+visible.length} of ${filtered.length}`:'No matching listings';
      const count=document.getElementById('catalogue-count');
      if(count)count.textContent=`${filtered.length} matching listing${filtered.length===1?'':'s'}`;
      const holder=document.getElementById('catalogue-pages');
      if(!holder)return;
      holder.replaceChildren();
      const add=(label,page,disabled=false,active=false)=>{
        const button=document.createElement('button');button.type='button';button.textContent=label;button.disabled=disabled;if(active)button.classList.add('active');
        button.onclick=()=>{cataloguePage=page;renderCatalogue();document.getElementById('catalogue-card')?.scrollIntoView({behavior:'smooth',block:'start'});};holder.appendChild(button);
      };
      add('Previous',cataloguePage-1,cataloguePage===1);
      let first=Math.max(1,cataloguePage-2),last=Math.min(pages,first+4);first=Math.max(1,last-4);
      for(let p=first;p<=last;p++)add(String(p),p,false,p===cataloguePage);
      add('Next',cataloguePage+1,cataloguePage===pages);
    }
    document.getElementById('catalogue-search')?.addEventListener('input',()=>{cataloguePage=1;renderCatalogue();});
    document.getElementById('catalogue-source')?.addEventListener('change',()=>{cataloguePage=1;renderCatalogue();});
    window.toggleAll=function(){
      const boxes=[...document.querySelectorAll('#catalogue-body .catalogue-row:not([hidden]) .product-select')];
      const select=!boxes.every(box=>box.checked);boxes.forEach(box=>box.checked=select);
    };
    renderCatalogue();
    '''
    page = page.replace('setInterval(refreshActivity,60000)', extra_js + '\n    setInterval(refreshActivity,60000)')
    return page


legacy.render_dashboard = render_dashboard
