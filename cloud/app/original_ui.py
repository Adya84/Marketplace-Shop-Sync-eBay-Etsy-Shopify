from __future__ import annotations

import html

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select

from .catalog_service import list_products
from .db import SessionLocal
from .models import MarketplaceConnection, Membership, SyncJob, User, Workspace

router = APIRouter()

APP_LOGO = "https://raw.githubusercontent.com/Adya84/Marketplace-Shop-Sync-eBay-Etsy-Shopify/main/marketplace_bridge/logo.png"
MARKET_PATHS = {
    "ebay": "M6.056 12.132v-4.92h1.2v3.026c.59-.703 1.402-.906 2.202-.906 1.34 0 2.828.904 2.828 2.855 0 .233-.015.457-.06.668.24-.953 1.274-1.305 2.896-1.344.51-.018 1.095-.018 1.56-.018v-.135c0-.885-.556-1.244-1.53-1.244-.72 0-1.245.3-1.305.81h-1.275c.136-1.29 1.5-1.62 2.686-1.62 1.064 0 1.995.27 2.415 1.02l-.436-.84h1.41l2.055 4.125 2.055-4.126H24l-3.72 7.305h-1.346l1.07-2.04-2.33-4.38c.13.255.2.555.2.93v2.46c0 .346.01.69.04 1.005H16.8a6.543 6.543 0 01-.046-.765c-.603.734-1.32.96-2.32.96-1.48 0-2.272-.78-2.272-1.695 0-.15.015-.284.037-.405-.3 1.246-1.36 2.086-2.767 2.086-.87 0-1.694-.315-2.2-.93 0 .24-.015.494-.04.734h-1.18c.02-.39.04-.855.04-1.245v-1.05h-4.83c.065 1.095.818 1.74 1.853 1.74.718 0 1.355-.3 1.568-.93h1.24c-.24 1.29-1.61 1.725-2.79 1.725C.95 15.009 0 13.822 0 12.232c0-1.754.982-2.91 3.116-2.91 1.688 0 2.93.886 2.94 2.806v.005z",
    "etsy": "M8.559 2.445c0-.325.033-.52.59-.52h7.465c1.3 0 2.02 1.11 2.54 3.193l.42 1.666h1.27c.23-4.728.43-6.784.43-6.784s-3.196.36-5.09.36H6.635L1.521.196v1.37l1.725.326c1.21.24 1.5.496 1.6 1.606 0 0 .11 3.27.11 8.64 0 5.385-.09 8.61-.09 8.61 0 .973-.39 1.333-1.59 1.573l-1.722.33V24l5.13-.165h8.55c1.935 0 6.39.165 6.39.165.105-1.17.75-6.48.855-7.064h-1.2l-1.284 2.91c-1.005 2.28-2.476 2.445-4.11 2.445h-4.906c-1.63 0-2.415-.64-2.415-2.05V12.8s3.62 0 4.79.096c.912.064 1.463.325 1.76 1.598l.39 1.695h1.41l-.09-4.278.192-4.305h-1.391l-.45 1.89c-.283 1.244-.48 1.47-1.754 1.6-1.666.17-4.815.14-4.815.14V2.45h-.05z",
    "shopify": "M15.337 23.979l7.216-1.561s-2.604-17.613-2.625-17.73c-.018-.116-.114-.192-.211-.192s-1.929-.136-1.929-.136-1.275-1.274-1.439-1.411-.211-.096-.29-.075L13.26 3.14c-.094-.27-.23-.542-.366-.773-.442-.75-1.1-1.157-1.873-1.157h-.075c-.02-.02-.04-.04-.06-.06C10.56.804 10.135.65 9.65.67 8.714.708 7.78 1.365 7.03 2.543c-.54.85-.95 1.93-1.062 2.778l-2.88.89c-.848.27-.868.29-.983 1.08C2.006 7.89 0 23.37 0 23.37l13.21 2.48 2.127-1.871z",
}
LABELS = {"shopify": "Shopify", "etsy": "Etsy", "ebay": "eBay"}


def esc(value: object) -> str:
    return html.escape(str(value or ""))


def market_logo(name: str, css: str = "market-logo") -> str:
    return f'<span class="{css} {css}-{name}" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="{MARKET_PATHS[name]}"/></svg></span>'


def context(request: Request):
    uid = str(request.session.get("user_id") or "")
    wid = str(request.session.get("workspace_id") or "")
    if not uid or not wid:
        return None
    with SessionLocal() as db:
        member = db.scalar(select(Membership).where(Membership.user_id == uid, Membership.workspace_id == wid))
        if not member:
            return None
        return db.get(User, uid), db.get(Workspace, wid), wid


def render_control_centre(request: Request) -> HTMLResponse:
    ctx = context(request)
    if not ctx:
        return RedirectResponse("/login", status_code=303)
    user, workspace, wid = ctx
    token = esc(request.session.get("csrf") or "")
    with SessionLocal() as db:
        connections = {r.provider: r for r in db.scalars(select(MarketplaceConnection).where(MarketplaceConnection.workspace_id == wid)).all()}
        jobs = db.scalars(select(SyncJob).where(SyncJob.workspace_id == wid).order_by(SyncJob.created_at.desc()).limit(20)).all()

    products = list_products(wid)
    rows = []
    for p in products:
        source = str(p.get("source") or "")
        sid = str(p.get("source_id") or "")
        mappings = p.get("mappings") or {}
        search = " ".join([str(p.get("title") or ""), source, sid, *[str(x) for x in p.get("skus") or []]]).casefold()
        actions = []
        if source != "shopify" and connections.get("shopify") and connections["shopify"].status == "connected":
            if mappings.get("shopify"):
                actions.append('<span class="pill ok">Completed</span>')
            else:
                actions.append(f'<form method="post" action="/sync/export/shopify/{esc(source)}/{esc(sid)}"><input type="hidden" name="csrf_token" value="{token}"><button>Create Shopify draft</button></form>')
        if source == "shopify":
            for dest in ("etsy", "ebay"):
                if connections.get(dest) and connections[dest].status == "connected":
                    actions.append(f'<a class="destination-btn {dest}-btn" href="/sync/reverse/{esc(sid)}/{dest}">{market_logo(dest,"button-market-logo")}<span>Export draft to {LABELS[dest]}</span></a>')
        rows.append(f'''<tr class="catalogue-row" data-search="{esc(search)}"><td>{market_logo(source,"row-market-logo") if source in MARKET_PATHS else ''}</td><td><strong class="product-title">{esc(p.get('title'))}</strong><small>{esc(source.title())} · {esc(sid)}</small></td><td>{esc(p.get('sku_summary')) or '<span class="muted-dash">—</span>'}<small>{int(p.get('variant_count') or 0)} variant{'s' if int(p.get('variant_count') or 0)!=1 else ''}</small></td><td><strong>{int(p.get('stock_total') or 0)}</strong></td><td>{'<span class="pill master-pill">Master</span>' if source=='shopify' else '<span class="pill">Imported</span>'}</td><td><div class="row-actions">{''.join(actions) or '<span class="muted-dash">—</span>'}</div></td></tr>''')

    cards = []
    for provider in ("ebay", "etsy", "shopify"):
        item = connections.get(provider)
        connected = bool(item and item.status == "connected")
        cards.append(f'''<section class="card"><h2 class="market-heading">{market_logo(provider)}<span>{'eBay UK' if provider=='ebay' else LABELS[provider]}</span></h2><div class="status"><i class="dot {'ok' if connected else ''}"></i>{'Connected' if connected else 'Not connected'}</div><p>{esc(item.account_label) if item and item.account_label else 'Connect your seller/store account to Shop Sync.'}</p><a class="button-link" href="/connect/{provider}">{'Manage' if connected else 'Connect'} {LABELS[provider]}</a></section>''')

    import_buttons = []
    for provider in ("ebay", "etsy", "shopify"):
        item = connections.get(provider)
        disabled = not (item and item.status == "connected")
        import_buttons.append(f'''<form method="post" action="/sync/import/{provider}"><input type="hidden" name="csrf_token" value="{token}"><button {'disabled' if disabled else ''}>{market_logo(provider,'button-market-logo')}<span>Import {LABELS[provider]}</span></button></form>''')

    job_rows = ''.join(f'<tr><td>{esc(j.kind.replace("_"," ").title())}</td><td>{esc(j.status)}</td><td>{esc(j.progress)}</td><td>{esc(j.message)}</td></tr>' for j in jobs) or '<tr><td colspan="4">No activity yet.</td></tr>'

    return HTMLResponse(f'''<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><meta charset="utf-8"><title>Shop Sync</title><style>
:root{{--premium-bg:#070d16;--premium-panel:#0e1725;--premium-panel-2:#111d2e;--premium-line:rgba(154,174,203,.15);--premium-text:#f5f8fc;--premium-muted:#98a9bf;--premium-green:#56d9ae;--premium-blue:#6eb7ff;--premium-shadow:0 18px 48px rgba(0,0,0,.26)}}*{{box-sizing:border-box}}body{{margin:0;background:radial-gradient(circle at 88% -10%,rgba(86,217,174,.12),transparent 28%),radial-gradient(circle at 8% 0%,rgba(110,183,255,.09),transparent 25%),linear-gradient(180deg,#08101b 0%,var(--premium-bg) 100%);color:var(--premium-text);font:15px system-ui,sans-serif}}main{{max-width:1480px;margin:auto;padding:30px 26px 42px}}h1{{font-size:31px;letter-spacing:-.035em;margin:0}}h2{{font-size:19px;margin:0 0 16px;letter-spacing:-.018em}}p,small{{color:var(--premium-muted)}}.hero{{display:flex;justify-content:space-between;align-items:center;margin-bottom:22px}}.brand-lockup{{display:flex;align-items:center;gap:17px}}.brand-logo-shell{{width:68px;height:68px;border-radius:17px;padding:6px;background:linear-gradient(145deg,rgba(255,255,255,.14),rgba(255,255,255,.035));border:1px solid rgba(255,255,255,.11);box-shadow:0 12px 32px rgba(0,0,0,.28);display:grid;place-items:center;overflow:hidden}}.brand-logo-shell img{{width:100%;height:100%;object-fit:contain;border-radius:12px}}.eyebrow{{display:block;color:var(--premium-green);font-size:10px;font-weight:800;letter-spacing:.18em;margin-bottom:5px}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:18px}}.card{{background:linear-gradient(180deg,rgba(17,29,46,.94),rgba(12,21,34,.97));border:1px solid var(--premium-line);border-radius:17px;padding:22px;margin-bottom:16px;box-shadow:var(--premium-shadow)}}.market-heading{{display:flex;align-items:center;gap:11px}}.market-logo,.row-market-logo{{width:30px;height:30px;border-radius:9px;display:inline-grid;place-items:center;background:rgba(255,255,255,.07);border:1px solid rgba(255,255,255,.08);flex:none}}.market-logo svg,.row-market-logo svg{{width:18px;height:18px;fill:currentColor}}.market-logo-etsy,.row-market-logo-etsy{{color:#f1641e}}.market-logo-shopify,.row-market-logo-shopify{{color:#95bf47}}.market-logo-ebay,.row-market-logo-ebay{{color:#f4f7fb}}.button-market-logo{{width:20px;height:20px;display:inline-grid;place-items:center;flex:none}}.button-market-logo svg{{width:16px;height:16px;fill:currentColor}}.status{{display:flex;gap:8px;align-items:center;margin:4px 0 16px;font-weight:650;color:#b8c7d9}}.dot{{width:10px;height:10px;background:#e85d75;border-radius:50%;box-shadow:0 0 0 4px rgba(232,93,117,.08)}}.dot.ok{{background:var(--premium-green);box-shadow:0 0 0 4px rgba(86,217,174,.09)}}button,.button-link,.destination-btn{{background:linear-gradient(135deg,#72bcff,#4c9fe9);border:0;color:#04111e;font-weight:700;border-radius:10px;padding:10px 14px;cursor:pointer;text-decoration:none;display:inline-flex;align-items:center;justify-content:center;gap:7px;box-shadow:0 8px 18px rgba(0,0,0,.16)}}button:disabled{{opacity:.4;cursor:not-allowed;box-shadow:none}}.etsy-btn{{background:linear-gradient(135deg,#f5844d,#e96525);color:white}}.ebay-btn{{background:linear-gradient(135deg,#4da5ff,#2b7bd1);color:white}}.actions,.row-actions{{display:flex;flex-wrap:wrap;gap:8px}}table{{width:100%;border-collapse:separate;border-spacing:0}}th{{color:#8ea1ba;text-transform:uppercase;font-size:10px;letter-spacing:.09em;font-weight:800}}td,th{{text-align:left;padding:13px 12px;border-top:1px solid rgba(154,174,203,.11);vertical-align:top}}tbody tr:hover{{background:rgba(255,255,255,.018)}}small{{display:block;margin-top:3px}}.pill{{background:#2d3b50;padding:4px 8px;border-radius:99px;font-size:12px;border:1px solid rgba(255,255,255,.07)}}.pill.ok{{background:#145c47;color:#9effd8}}.master-pill{{background:rgba(149,191,71,.13);color:#c9ed83;border-color:rgba(149,191,71,.24)}}.catalogue-tools{{display:flex;gap:10px;flex-wrap:wrap;align-items:center;background:rgba(5,11,19,.3);border:1px solid rgba(154,174,203,.1);border-radius:12px;padding:13px;margin-bottom:12px}}.catalogue-tools input{{flex:1;min-width:220px;background:#091321;color:var(--premium-text);border:1px solid rgba(154,174,203,.2);border-radius:10px;padding:10px 12px}}.muted-dash{{color:#697b90}}.footer{{text-align:center;color:var(--premium-muted);font-size:12px;padding:18px 0 4px;opacity:.72}}.user-tools{{display:flex;align-items:center;gap:10px;flex-wrap:wrap}}.user-badge{{color:#b8c7d9;font-size:12px}}@media(max-width:760px){{main{{padding:18px 13px 32px}}.hero{{align-items:flex-start;gap:12px;flex-direction:column}}.brand-logo-shell{{width:56px;height:56px}}table{{display:block;overflow:auto}}}}
</style></head><body><main><div class="hero"><div class="brand-lockup"><div class="brand-logo-shell"><img src="{APP_LOGO}" alt="Shop Sync"></div><div><span class="eyebrow">MARKETPLACE CONTROL CENTRE</span><h1>Shop Sync</h1><p>Hosted edition · One catalogue, every marketplace · {esc(workspace.name)}</p></div></div><div class="user-tools"><span class="user-badge">{esc(user.email)}</span><form method="post" action="/logout"><input type="hidden" name="csrf_token" value="{token}"><button>Sign out</button></form></div></div>
<div class="grid">{''.join(cards)}</div>
<section class="card"><h2>Import catalogues</h2><div class="actions">{''.join(import_buttons)}</div></section>
<section class="card"><div class="hero"><div><span class="eyebrow">CATALOGUE</span><h2>Product workspace</h2></div></div><div class="catalogue-tools"><input id="catalogue-search" placeholder="Search title, marketplace, listing ID or SKU" oninput="filterCatalogue()"><span id="catalogue-count">{len(rows)} products</span></div><table><thead><tr><th>Market</th><th>Listing</th><th>SKU / Variants</th><th>Qty</th><th>Status</th><th>Action</th></tr></thead><tbody id="catalogue-body">{''.join(rows) or '<tr><td colspan="6">No products imported yet.</td></tr>'}</tbody></table></section>
<section class="card"><div class="hero"><h2>Activity</h2><form method="post" action="/sync/activity/clear"><input type="hidden" name="csrf_token" value="{token}"><button>Clear activity</button></form></div><table><thead><tr><th>Job</th><th>Status</th><th>Progress</th><th>Message</th></tr></thead><tbody id="activity-rows">{job_rows}</tbody></table><small>Updates automatically every 60 seconds.</small></section>
<footer class="footer">Copyright © 2026 Adrian Apel · All rights reserved</footer>
<script>
function filterCatalogue(){{const q=document.getElementById('catalogue-search').value.trim().toLowerCase();let shown=0;document.querySelectorAll('.catalogue-row').forEach(row=>{{const show=!q||row.dataset.search.includes(q);row.style.display=show?'':'none';if(show)shown++}});document.getElementById('catalogue-count').textContent=shown+' product'+(shown===1?'':'s')}}
async function refreshActivity(){{try{{const r=await fetch('/cloud-status',{{cache:'no-store'}});if(!r.ok)return;const data=await r.json();const body=document.getElementById('activity-rows');body.replaceChildren();if(!data.jobs.length){{const tr=document.createElement('tr');const td=document.createElement('td');td.colSpan=4;td.textContent='No activity yet.';tr.appendChild(td);body.appendChild(tr);return}}data.jobs.forEach(job=>{{const tr=document.createElement('tr');[job.kind.replaceAll('_',' ').replace(/\\b\\w/g,c=>c.toUpperCase()),job.status,job.progress,job.message].forEach(value=>{{const td=document.createElement('td');td.textContent=String(value??'');tr.appendChild(td)}});body.appendChild(tr)}})}}catch(e){{console.warn('Activity refresh failed',e)}}}}
setInterval(refreshActivity,60000);
</script></main></body></html>''')


@router.get("/cloud-status")
def cloud_status(request: Request):
    ctx = context(request)
    if not ctx:
        return {"jobs": []}
    _, _, wid = ctx
    with SessionLocal() as db:
        jobs = db.scalars(select(SyncJob).where(SyncJob.workspace_id == wid).order_by(SyncJob.created_at.desc()).limit(20)).all()
    return {"jobs": [{"kind": j.kind, "status": j.status, "progress": j.progress, "message": j.message} for j in jobs]}
