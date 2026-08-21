from __future__ import annotations

import asyncio
import html
import re
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi.responses import FileResponse, HTMLResponse

from . import main as core
from . import main_v6 as v6

app = v6.app
app.version = "0.0.32"

_previous_lifespan = app.router.lifespan_context
_recovery_tasks: set[asyncio.Task] = set()


# Simple Icons paths are embedded so marketplace branding works even when the
# Home Assistant host has no direct internet access.
_MARKET_PATHS = {
    "ebay": "M6.056 12.132v-4.92h1.2v3.026c.59-.703 1.402-.906 2.202-.906 1.34 0 2.828.904 2.828 2.855 0 .233-.015.457-.06.668.24-.953 1.274-1.305 2.896-1.344.51-.018 1.095-.018 1.56-.018v-.135c0-.885-.556-1.244-1.53-1.244-.72 0-1.245.3-1.305.81h-1.275c.136-1.29 1.5-1.62 2.686-1.62 1.064 0 1.995.27 2.415 1.02l-.436-.84h1.41l2.055 4.125 2.055-4.126H24l-3.72 7.305h-1.346l1.07-2.04-2.33-4.38c.13.255.2.555.2.93v2.46c0 .346.01.69.04 1.005H16.8a6.543 6.543 0 01-.046-.765c-.603.734-1.32.96-2.32.96-1.48 0-2.272-.78-2.272-1.695 0-.15.015-.284.037-.405-.3 1.246-1.36 2.086-2.767 2.086-.87 0-1.694-.315-2.2-.93 0 .24-.015.494-.04.734h-1.18c.02-.39.04-.855.04-1.245v-1.05h-4.83c.065 1.095.818 1.74 1.853 1.74.718 0 1.355-.3 1.568-.93h1.24c-.24 1.29-1.61 1.725-2.79 1.725C.95 15.009 0 13.822 0 12.232c0-1.754.982-2.91 3.116-2.91 1.688 0 2.93.886 2.94 2.806v.005zm9.137.183c-1.095.034-1.77.233-1.77.95 0 .465.36.97 1.305.97 1.26 0 1.935-.69 1.935-1.814v-.13c-.45 0-.99.006-1.484.022h.012zm-6.06 1.875c1.11 0 1.876-.806 1.876-2.02s-.768-2.02-1.893-2.02c-1.11 0-1.89.806-1.89 2.02s.765 2.02 1.875 2.02h.03zm-4.35-2.514c-.044-1.125-.854-1.546-1.725-1.546-.944 0-1.694.474-1.815 1.546z",
    "etsy": "M8.559 2.445c0-.325.033-.52.59-.52h7.465c1.3 0 2.02 1.11 2.54 3.193l.42 1.666h1.27c.23-4.728.43-6.784.43-6.784s-3.196.36-5.09.36H6.635L1.521.196v1.37l1.725.326c1.21.24 1.5.496 1.6 1.606 0 0 .11 3.27.11 8.64 0 5.385-.09 8.61-.09 8.61 0 .973-.39 1.333-1.59 1.573l-1.722.33V24l5.13-.165h8.55c1.935 0 6.39.165 6.39.165.105-1.17.75-6.48.855-7.064h-1.2l-1.284 2.91c-1.005 2.28-2.476 2.445-4.11 2.445h-4.906c-1.63 0-2.415-.64-2.415-2.05V12.8s3.62 0 4.79.096c.912.064 1.463.325 1.76 1.598l.39 1.695h1.41l-.09-4.278.192-4.305h-1.391l-.45 1.89c-.283 1.244-.48 1.47-1.754 1.6-1.666.17-4.815.14-4.815.14V2.45h-.05z",
    "shopify": "M15.337 23.979l7.216-1.561s-2.604-17.613-2.625-17.73c-.018-.116-.114-.192-.211-.192s-1.929-.136-1.929-.136-1.275-1.274-1.439-1.411c-.045-.037-.075-.057-.121-.074l-.914 21.104h.023zM11.71 11.305s-.81-.424-1.774-.424c-1.447 0-1.504.906-1.504 1.141 0 1.232 3.24 1.715 3.24 4.629 0 2.295-1.44 3.76-3.406 3.76-2.354 0-3.54-1.465-3.54-1.465l.646-2.086s1.245 1.066 2.28 1.066c.675 0 .975-.545.975-.932 0-1.619-2.654-1.694-2.654-4.359-.034-2.237 1.571-4.416 4.827-4.416 1.257 0 1.875.361 1.875.361l-.945 2.715-.02.01zM11.17.83c.136 0 .271.038.405.135-.984.465-2.064 1.639-2.508 3.992-.656.213-1.293.405-1.889.578C7.697 3.75 8.951.84 11.17.84V.83zm1.235 2.949v.135c-.754.232-1.583.484-2.394.736.466-1.777 1.333-2.645 2.085-2.971.193.501.309 1.176.309 2.1zm.539-2.234c.694.074 1.141.867 1.429 1.755-.349.114-.735.231-1.158.366v-.252c0-.752-.096-1.371-.271-1.871v.002zm2.992 1.289c-.02 0-.06.021-.078.021s-.289.075-.714.21c-.423-1.233-1.176-2.37-2.508-2.37h-.115C12.135.209 11.669 0 11.265 0 8.159 0 6.675 3.877 6.21 5.846c-1.194.365-2.063.636-2.16.674-.675.213-.694.232-.772.87-.075.462-1.83 14.063-1.83 14.063L15.009 24l.927-21.166z",
    # TikTok is intentionally represented by its familiar musical-note mark.
    "tiktok": "M18.98 6.58a5.46 5.46 0 0 1-3.19-1.02v8.05a6.58 6.58 0 1 1-5.68-6.52v3.3a3.36 3.36 0 1 0 2.36 3.22V0h3.32c.16 1.74 1.43 3.15 3.19 3.52v3.06z",
}


def _market_logo(name: str, css: str = "market-logo") -> str:
    path = _MARKET_PATHS[name]
    return f'<span class="{css} {css}-{name}" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="{path}"/></svg></span>'


def _import_runner(kind: str):
    return {
        "ebay_import": core.run_ebay_import,
        "etsy_import": core.run_etsy_import,
        "shopify_import": core.run_shopify_import,
        "tiktok_import": core.run_tiktok_import,
    }.get(kind)


@asynccontextmanager
async def recovery_lifespan(application):
    async with _previous_lifespan(application):
        stale = [
            job
            for job in core.db.list_jobs(5000)
            if str(job.get("status")) in {"running", "queued"}
        ]

        for job in stale:
            job_id = int(job["id"])
            kind = str(job.get("kind") or "")
            runner = _import_runner(kind)
            if runner is None:
                core.db.update_job(
                    job_id,
                    status="failed",
                    message="Interrupted by Shop Sync restart. Review this write/export before retrying so a marketplace listing is not duplicated.",
                )
                continue

            core.db.update_job(
                job_id,
                status="queued",
                progress=0,
                total=0,
                message="Recovered after Shop Sync restart — restarting this import safely from the beginning.",
            )
            task = asyncio.create_task(runner(job_id), name=f"shopsync-recover-{kind}-{job_id}")
            _recovery_tasks.add(task)
            task.add_done_callback(_recovery_tasks.discard)
        yield


app.router.lifespan_context = recovery_lifespan


@app.get("/assets/logo.png")
def shop_sync_logo():
    path = Path("/app/logo.png")
    if not path.exists():
        return HTMLResponse("", status_code=404)
    return FileResponse(path, media_type="image/png", headers={"Cache-Control": "public, max-age=86400"})


def _shopify_rows() -> str:
    esc = html.escape
    rows: list[str] = []
    for row in core.db.list_products():
        if row.get("source") != "shopify":
            continue
        source_id = str(row.get("source_id") or "")
        title = str(row.get("title") or "")
        skus = row.get("skus") or []
        search_value = " ".join([title, "shopify", source_id, *[str(v) for v in skus]]).casefold()
        variants = int(row.get("variant_count") or 0)
        stock = int(row.get("stock_total") or 0)
        sku_summary = str(row.get("sku_summary") or "")
        variant_note = f"{variants} variant{'s' if variants != 1 else ''}" if variants else "No variants"
        sid = esc(source_id, quote=True)
        rows.append(
            f'''<tr class="catalogue-row shopify-master-row" data-source="shopify" data-search="{esc(search_value, quote=True)}">
              <td>{_market_logo('shopify','row-market-logo')}</td>
              <td><strong class="product-title">{esc(title)}</strong><small>Shopify · {esc(source_id)}</small></td>
              <td>{esc(sku_summary) if sku_summary else '<span class="muted-dash">—</span>'}<small>{esc(variant_note)}</small></td>
              <td><strong>{stock}</strong></td>
              <td><span class="pill master-pill">Master</span></td>
              <td><div class="row-actions"><button class="destination-btn etsy-btn" onclick="reversePlan('{sid}','etsy')">{_market_logo('etsy','button-market-logo')}<span>Export draft to Etsy</span></button><button class="destination-btn ebay-btn" onclick="reversePlan('{sid}','ebay')">{_market_logo('ebay','button-market-logo')}<span>Export draft to eBay</span></button></div></td>
            </tr>'''
        )
    return "".join(rows)


def _inject_shopify_workspace(page: str) -> str:
    rows = _shopify_rows()
    match = re.search(r'(<tbody id="catalogue-body">)(.*?)(</tbody>)', page, re.S)
    if match and rows:
        page = page[:match.start()] + match.group(1) + match.group(2) + rows + match.group(3) + page[match.end():]

    page = page.replace("<h2>Ready to send</h2>", "<h2>Product workspace</h2>", 1)
    page = page.replace(
        '<div><button onclick="toggleAll()">Select page</button> <button onclick="createSelected()">Create selected drafts</button></div>',
        '<div class="workspace-actions"><button onclick="toggleAll()">Select marketplace page</button> <button onclick="createSelected()">Create Shopify drafts</button></div>',
        1,
    )

    # v6 has a separate Shopify reverse table. Product actions now live in the
    # unified workspace; retain only the marketplace-specific defaults/settings.
    pattern = re.compile(r'<section class="card"><h2>Reverse Sync — Shopify → Etsy / eBay</h2>.*?</section>', re.S)
    found = pattern.search(page)
    if found:
        old = found.group(0)
        details = re.search(r'(<details>.*?</details>)', old, re.S)
        replacement = ""
        if details:
            replacement = (
                '<section class="card export-settings-card"><div class="premium-section-heading">'
                '<div><span class="eyebrow">MARKETPLACE RULES</span><h2>Export settings</h2>'
                '<p>Destination-specific defaults used when Shopify does not contain an Etsy or eBay requirement.</p></div>'
                '<span class="settings-badge">Advanced</span></div>' + details.group(1) + '</section>'
            )
        page = page[:found.start()] + replacement + page[found.end():]
    return page


def _brand_connections(page: str) -> str:
    replacements = {
        "<h2>eBay UK</h2>": f'<h2 class="market-heading">{_market_logo("ebay")}<span>eBay UK</span></h2>',
        "<h2>Etsy</h2>": f'<h2 class="market-heading">{_market_logo("etsy")}<span>Etsy</span></h2>',
        "<h2>Shopify</h2>": f'<h2 class="market-heading">{_market_logo("shopify")}<span>Shopify</span></h2>',
        "<h2>TikTok Shop</h2>": f'<h2 class="market-heading">{_market_logo("tiktok")}<span>TikTok Shop</span></h2>',
        "Import eBay listings": f'{_market_logo("ebay","button-market-logo")}<span>Import eBay</span>',
        "Import Etsy listings": f'{_market_logo("etsy","button-market-logo")}<span>Import Etsy</span>',
        "Import Shopify products": f'{_market_logo("shopify","button-market-logo")}<span>Import Shopify</span>',
        "Import TikTok Shop listings": f'{_market_logo("tiktok","button-market-logo")}<span>Import TikTok</span>',
    }
    for old, new in replacements.items():
        page = page.replace(old, new, 1)
    return page


def _brand_header(page: str) -> str:
    replacement = '''<div class="brand-lockup"><div class="brand-logo-shell"><img src="assets/logo.png" alt="Shop Sync"></div><div><span class="eyebrow">MARKETPLACE CONTROL CENTRE</span><h1>Shop Sync</h1><p>Version ''' + html.escape(app.version) + ''' · One catalogue, every marketplace</p></div></div>'''
    page = re.sub(r'<div><h1>Shop Sync</h1><p>Version .*?</p></div>', replacement, page, count=1, flags=re.S)
    return page


def _premium_styles(page: str) -> str:
    css = r'''
    <style id="shopsync-premium">
    :root{--premium-bg:#070d16;--premium-panel:#0e1725;--premium-panel-2:#111d2e;--premium-line:rgba(154,174,203,.15);--premium-text:#f5f8fc;--premium-muted:#98a9bf;--premium-green:#56d9ae;--premium-blue:#6eb7ff;--premium-shadow:0 18px 48px rgba(0,0,0,.26)}
    body{background:radial-gradient(circle at 88% -10%,rgba(86,217,174,.12),transparent 28%),radial-gradient(circle at 8% 0%,rgba(110,183,255,.09),transparent 25%),linear-gradient(180deg,#08101b 0%,var(--premium-bg) 100%);color:var(--premium-text)}
    main{max-width:1480px;padding:30px 26px 42px}
    .hero:first-child{padding:10px 2px 6px;margin-bottom:22px}.brand-lockup{display:flex;align-items:center;gap:17px}.brand-logo-shell{width:68px;height:68px;border-radius:17px;padding:6px;background:linear-gradient(145deg,rgba(255,255,255,.14),rgba(255,255,255,.035));border:1px solid rgba(255,255,255,.11);box-shadow:0 12px 32px rgba(0,0,0,.28);display:grid;place-items:center;overflow:hidden}.brand-logo-shell img{width:100%;height:100%;object-fit:contain;border-radius:12px}.eyebrow{display:block;color:var(--premium-green);font-size:10px;font-weight:800;letter-spacing:.18em;margin-bottom:5px}.brand-lockup h1{font-size:31px;letter-spacing:-.035em}.brand-lockup p{margin:4px 0 0}
    .card{background:linear-gradient(180deg,rgba(17,29,46,.94),rgba(12,21,34,.97));border:1px solid var(--premium-line);border-radius:17px;padding:22px;box-shadow:var(--premium-shadow);backdrop-filter:blur(8px)}.grid{gap:18px}.grid>.card{position:relative;overflow:hidden}.grid>.card:before{content:"";position:absolute;inset:0 auto auto 0;width:100%;height:1px;background:linear-gradient(90deg,transparent,rgba(255,255,255,.16),transparent)}
    h2{letter-spacing:-.018em}.market-heading{display:flex;align-items:center;gap:11px;font-size:19px}.market-logo,.row-market-logo{width:30px;height:30px;border-radius:9px;display:inline-grid;place-items:center;background:rgba(255,255,255,.07);border:1px solid rgba(255,255,255,.08);flex:none}.market-logo svg{width:18px;height:18px;fill:currentColor}.market-logo-ebay{color:#f4f7fb}.market-logo-etsy{color:#f1641e}.market-logo-shopify{color:#95bf47}.market-logo-tiktok{color:#f4f7fb}
    .status{margin:4px 0 16px;font-weight:650;color:#b8c7d9}.dot{box-shadow:0 0 0 4px rgba(232,93,117,.08)}.dot.ok{box-shadow:0 0 0 4px rgba(86,217,174,.09)}
    button,.button-link{border-radius:10px;padding:10px 14px;transition:transform .15s ease,box-shadow .15s ease,filter .15s ease;box-shadow:0 8px 18px rgba(0,0,0,.16)}button:hover,.button-link:hover{transform:translateY(-1px);filter:brightness(1.06)}button:disabled{transform:none;box-shadow:none}.button-link{background:linear-gradient(135deg,#72bcff,#4c9fe9)}
    input,select,textarea{border-radius:10px!important;background:#091321!important;border:1px solid rgba(154,174,203,.2)!important;outline:none}input:focus,select:focus,textarea:focus{border-color:rgba(110,183,255,.6)!important;box-shadow:0 0 0 3px rgba(110,183,255,.08)}
    .button-market-logo{width:20px;height:20px;display:inline-grid;place-items:center;flex:none}.button-market-logo svg{width:16px;height:16px;fill:currentColor}button .button-market-logo+span{margin-left:7px}button:has(.button-market-logo){display:inline-flex;align-items:center;justify-content:center}.button-market-logo-ebay{color:inherit}.button-market-logo-etsy{color:inherit}.button-market-logo-shopify{color:inherit}.button-market-logo-tiktok{color:inherit}
    table{border-collapse:separate;border-spacing:0}th{color:#8ea1ba;text-transform:uppercase;font-size:10px;letter-spacing:.09em;font-weight:800}td,th{padding:13px 12px;border-top:1px solid rgba(154,174,203,.11)}tbody tr{transition:background .15s ease}tbody tr:hover{background:rgba(255,255,255,.018)}.product-title{font-size:14px}.shopify-master-row{background:linear-gradient(90deg,rgba(149,191,71,.045),transparent 42%)}.row-market-logo{width:32px;height:32px}.row-market-logo svg{width:18px;height:18px;fill:currentColor}.row-market-logo-shopify{color:#95bf47}
    .pill{border:1px solid rgba(255,255,255,.07)}.master-pill{background:rgba(149,191,71,.13);color:#c9ed83;border-color:rgba(149,191,71,.24)}.row-actions{display:flex;flex-wrap:wrap;gap:7px}.destination-btn{font-size:12px;padding:8px 10px}.etsy-btn{background:linear-gradient(135deg,#f5844d,#e96525);color:white}.ebay-btn{background:linear-gradient(135deg,#4da5ff,#2b7bd1);color:white}
    .catalogue-tools{background:rgba(5,11,19,.3);border:1px solid rgba(154,174,203,.1);border-radius:12px;padding:13px}.workspace-actions{display:flex;flex-wrap:wrap;gap:7px}.catalogue-footer{padding-top:4px}.catalogue-pages button{box-shadow:none;background:#16243a;color:#c9d7e8}.catalogue-pages button.active{background:linear-gradient(135deg,#5ddbb1,#38b98f);color:#052116}
    .activity-live{border-radius:14px!important}.job-status{font-weight:700}.premium-section-heading{display:flex;align-items:flex-start;justify-content:space-between;gap:14px;margin-bottom:12px}.premium-section-heading h2{margin:0}.premium-section-heading p{margin:4px 0 0;max-width:760px}.settings-badge{font-size:11px;color:#b6c7db;background:rgba(255,255,255,.06);border:1px solid rgba(255,255,255,.08);border-radius:99px;padding:6px 9px}
    details{border:1px solid rgba(154,174,203,.12);border-radius:12px;padding:12px;background:rgba(4,10,18,.22)}summary{cursor:pointer;font-weight:700;color:#d8e4f2}.footer{opacity:.72;padding-top:18px}
    @media(max-width:760px){main{padding:18px 13px 32px}.brand-logo-shell{width:56px;height:56px;border-radius:14px}.brand-lockup h1{font-size:26px}.hero:first-child{align-items:flex-start}.row-actions{min-width:170px}.premium-section-heading{display:block}.settings-badge{display:inline-block;margin-top:9px}}
    </style>
    '''
    return page.replace("</head>", css + "</head>", 1)


# main_v6 already owns the dashboard route. Replace it with the polished v7 view.
v6.v5._drop_route("/", "GET")


@app.get("/", response_class=HTMLResponse)
def dashboard():
    response = v6.dashboard()
    page = response.body.decode("utf-8")
    page = _inject_shopify_workspace(page)
    page = _brand_connections(page)
    page = _brand_header(page)
    page = _premium_styles(page)
    return HTMLResponse(page)
