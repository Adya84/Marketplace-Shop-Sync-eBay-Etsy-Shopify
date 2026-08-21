from __future__ import annotations

import html
from typing import Any

from fastapi import BackgroundTasks, Form, HTTPException
from fastapi.responses import HTMLResponse

from . import main as core
from . import main_v2 as v2
from .settings import settings

app = v2.app
app.version = "0.0.28"


def _drop_route(path: str, method: str) -> None:
    method = method.upper()
    app.router.routes[:] = [
        route
        for route in app.router.routes
        if not (getattr(route, "path", None) == path and method in (getattr(route, "methods", set()) or set()))
    ]


def _find_job(job_id: int) -> dict[str, Any] | None:
    return next((job for job in core.db.list_jobs(5000) if int(job["id"]) == int(job_id)), None)


async def _run_single_export(job_id: int, source: str, source_id: str) -> bool:
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
        client = core.ShopifyClient(
            credential["shop_domain"],
            settings.shopify_api_version,
            client_id=credential["client_id"],
            client_secret=credential["client_secret"],
        )
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


core.run_shopify_export = _run_single_export


async def _run_bulk_export(parent_job_id: int, items: list[tuple[str, str]]) -> None:
    total = len(items)
    completed = 0
    failed = 0
    core.db.update_job(
        parent_job_id,
        status="running",
        progress=0,
        total=total,
        message=f"Starting Shopify bulk transfer · 0 completed · 0 failed · {total} remaining",
    )
    for index, (source, source_id) in enumerate(items, 1):
        product = core.db.get_product(source, source_id) or {}
        title = str(product.get("title") or source_id)
        remaining = total - index + 1
        core.db.update_job(
            parent_job_id,
            status="running",
            progress=index - 1,
            total=total,
            message=(
                f"Creating {index}/{total}: {source.title()} · {title} · "
                f"{completed} completed · {failed} failed · {remaining} remaining"
            ),
        )
        child_job_id = core.db.create_job("shopify_export")
        ok = await _run_single_export(child_job_id, source, source_id)
        if ok:
            completed += 1
        else:
            failed += 1
        core.db.update_job(
            parent_job_id,
            progress=index,
            total=total,
            message=(
                f"Processed {index}/{total} · {completed} completed · {failed} failed · "
                f"{total - index} remaining"
            ),
        )

    final_status = "failed" if failed == total and total else "complete"
    core.db.update_job(
        parent_job_id,
        status=final_status,
        progress=total,
        total=total,
        message=f"Bulk transfer finished · {completed} completed · {failed} failed",
    )


_drop_route("/api/products/shopify/bulk", "POST")


@app.post("/api/products/shopify/bulk")
def export_shopify_bulk(background_tasks: BackgroundTasks, selected: list[str] = Form(...)):
    core.get_credentials("shopify")
    if not selected:
        raise HTTPException(400, "Select at least one product")

    items: list[tuple[str, str]] = []
    for key in dict.fromkeys(selected):
        try:
            source, source_id = key.split(":", 1)
        except ValueError as exc:
            raise HTTPException(400, "Invalid product selection") from exc
        if not core.db.get_product(source, source_id):
            raise HTTPException(404, f"Product not found: {source} {source_id}")
        if core.db.duplicate_is_blocked(source, source_id, "shopify"):
            raise HTTPException(409, f"Duplicate title requires review: {source} {source_id}")
        items.append((source, source_id))

    parent_job_id = core.db.create_job("shopify_bulk")
    core.db.update_job(parent_job_id, total=len(items), message=f"Queued {len(items)} Shopify drafts")
    background_tasks.add_task(_run_bulk_export, parent_job_id, items)
    return {"job_id": parent_job_id, "count": len(items)}


def _activity_snapshot(jobs: list[dict[str, Any]]) -> dict[str, Any]:
    active = [job for job in jobs if job.get("status") in {"running", "queued"}]
    running_bulk = next((job for job in active if job.get("kind") == "shopify_bulk" and job.get("status") == "running"), None)
    running = running_bulk or next((job for job in active if job.get("status") == "running"), None)
    current = running or (active[0] if active else None)
    if not current:
        return {
            "active": False,
            "status": "idle",
            "kind": "",
            "message": "No job is currently running.",
            "progress": 0,
            "total": 0,
            "percent": 0,
            "updated_at": "",
            "queued": 0,
            "running": 0,
        }
    progress = int(current.get("progress") or 0)
    total = int(current.get("total") or 0)
    percent = round((progress / total) * 100) if total else 0
    return {
        "active": True,
        "status": str(current.get("status") or ""),
        "kind": str(current.get("kind") or ""),
        "message": str(current.get("message") or ""),
        "progress": progress,
        "total": total,
        "percent": percent,
        "updated_at": str(current.get("updated_at") or ""),
        "queued": sum(1 for job in active if job.get("status") == "queued"),
        "running": sum(1 for job in active if job.get("status") == "running"),
    }


_drop_route("/api/status", "GET")


@app.get("/api/status")
def status():
    jobs = core.db.list_jobs(5000)
    return {
        "ebay_connected": core.db.get_credential("ebay") is not None,
        "etsy_connected": core.db.get_credential("etsy") is not None,
        "shopify_connected": core.db.get_credential("shopify") is not None,
        "tiktok_connected": core.db.get_credential("tiktok") is not None,
        "products": len(core.db.list_products()),
        "jobs": jobs,
        "activity": _activity_snapshot(jobs),
    }


def _activity_section() -> str:
    return '''<section class="card" id="activity-card">
      <div class="hero"><div><h2>Activity</h2><p>Live transfer progress and full job history.</p></div>
      <div><button onclick="refreshActivityV28()">Refresh now</button> <button onclick="clearActivity()">Clear finished</button></div></div>
      <div id="activity-live" class="activity-live idle">
        <div class="activity-live-head"><span id="activity-live-badge" class="live-badge">IDLE</span><strong id="activity-live-title">Nothing running</strong><span id="activity-live-age">—</span></div>
        <div id="activity-live-message" class="activity-live-message">No job is currently running.</div>
        <div class="activity-progress"><span id="activity-progress-bar"></span></div>
        <div class="activity-stats"><span id="activity-progress-text">0 / 0</span><span id="activity-percent">0%</span><span id="activity-workers">0 running · 0 queued</span></div>
      </div>
      <div class="activity-history-head"><h3>History</h3><span id="activity-history-count">0 jobs</span></div>
      <div class="table-wrap"><table><thead><tr><th>Job</th><th>Status</th><th>Progress</th><th>Message</th><th>Updated</th></tr></thead>
      <tbody id="activity-history-rows"><tr><td colspan="5">Loading activity…</td></tr></tbody></table></div>
      <div class="catalogue-footer"><span id="activity-range"></span><div id="activity-pages" class="catalogue-pages"></div></div>
      <small>Live activity refreshes every 2 seconds. History shows 25 jobs per page.</small>
    </section>'''


def _upgrade_page(page: str) -> str:
    activity_start = '<section class="card"><div class="hero"><h2>Activity</h2>'
    footer_start = '<footer class="footer">'
    start = page.find(activity_start)
    end = page.find(footer_start, start)
    if start != -1 and end != -1:
        page = page[:start] + _activity_section() + page[end:]

    css = '''
    .activity-live{border:1px solid var(--line);border-radius:12px;padding:16px;background:#0c1625;margin-bottom:18px}
    .activity-live.active{border-color:#2f7f63}.activity-live-head{display:flex;gap:10px;align-items:center;flex-wrap:wrap}.activity-live-head #activity-live-age{margin-left:auto;color:var(--muted);font-size:12px}
    .live-badge{font-size:11px;font-weight:800;letter-spacing:.08em;padding:4px 8px;border-radius:999px;background:#2d3b50}.activity-live.active .live-badge{background:#145c47;color:#9effd8}
    .activity-live-message{font-size:16px;margin:12px 0 10px;overflow-wrap:anywhere}.activity-progress{height:10px;background:#08101b;border-radius:99px;overflow:hidden;border:1px solid var(--line)}.activity-progress span{display:block;height:100%;width:0%;background:var(--green);transition:width .25s ease}
    .activity-stats{display:flex;gap:18px;flex-wrap:wrap;color:var(--muted);font-size:12px;margin-top:8px}.activity-history-head{display:flex;justify-content:space-between;align-items:center;margin-top:4px}.activity-history-head h3{font-size:15px;margin:0 0 8px}.activity-history-head span{color:var(--muted);font-size:12px}
    .job-status{font-weight:700;text-transform:capitalize}.job-status.failed{color:#ff8699}.job-status.complete{color:#9effd8}.job-status.running{color:#75c6ff}.job-status.queued{color:#ffd78c}
    '''
    page = page.replace('</style>', css + '</style>', 1)

    js = r'''
    <script>
    let activityJobs=[];
    let activityPage=1;
    const ACTIVITY_PAGE_SIZE=25;
    function activityLabel(kind){return String(kind||'').replaceAll('_',' ').replace(/\b\w/g,c=>c.toUpperCase())}
    function activityAge(value){
      if(!value)return '—'; const seconds=Math.max(0,Math.floor((Date.now()-new Date(value).getTime())/1000));
      if(seconds<5)return 'updated just now'; if(seconds<60)return `updated ${seconds}s ago`; const mins=Math.floor(seconds/60); if(mins<60)return `updated ${mins}m ago`; return new Date(value).toLocaleString();
    }
    function renderActivityLive(activity){
      const box=document.getElementById('activity-live'); if(!box)return;
      const active=Boolean(activity&&activity.active); box.classList.toggle('active',active); box.classList.toggle('idle',!active);
      document.getElementById('activity-live-badge').textContent=active?'LIVE':'IDLE';
      document.getElementById('activity-live-title').textContent=active?activityLabel(activity.kind):'Nothing running';
      document.getElementById('activity-live-message').textContent=(activity&&activity.message)||'No job is currently running.';
      const progress=Number(activity?.progress||0), total=Number(activity?.total||0), percent=Number(activity?.percent||0);
      document.getElementById('activity-progress-bar').style.width=`${Math.max(0,Math.min(100,percent))}%`;
      document.getElementById('activity-progress-text').textContent=total?`${progress} / ${total}`:'Waiting for total…';
      document.getElementById('activity-percent').textContent=`${percent}%`;
      document.getElementById('activity-workers').textContent=`${Number(activity?.running||0)} running · ${Number(activity?.queued||0)} queued`;
      document.getElementById('activity-live-age').textContent=activityAge(activity?.updated_at);
    }
    function activityPageButton(label,page,disabled=false,active=false){
      const button=document.createElement('button'); button.textContent=label; button.disabled=disabled; if(active)button.classList.add('active');
      button.onclick=()=>{activityPage=page;renderActivityHistory()}; return button;
    }
    function renderActivityHistory(){
      const body=document.getElementById('activity-history-rows'); if(!body)return; body.replaceChildren();
      const total=activityJobs.length, pages=Math.max(1,Math.ceil(total/ACTIVITY_PAGE_SIZE)); activityPage=Math.min(Math.max(1,activityPage),pages);
      const start=(activityPage-1)*ACTIVITY_PAGE_SIZE, pageJobs=activityJobs.slice(start,start+ACTIVITY_PAGE_SIZE);
      if(!pageJobs.length){const row=document.createElement('tr'),cell=document.createElement('td');cell.colSpan=5;cell.textContent='No activity yet.';row.appendChild(cell);body.appendChild(row)}
      pageJobs.forEach(job=>{
        const row=document.createElement('tr');
        const values=[activityLabel(job.kind),String(job.status||''),`${Number(job.progress||0)}/${Number(job.total||0)}`,String(job.message||''),activityAge(job.updated_at)];
        values.forEach((value,index)=>{const cell=document.createElement('td');cell.textContent=value;if(index===1)cell.className=`job-status ${String(job.status||'')}`;row.appendChild(cell)});body.appendChild(row)
      });
      document.getElementById('activity-history-count').textContent=`${total} job${total===1?'':'s'}`;
      document.getElementById('activity-range').textContent=total?`Showing ${start+1}–${Math.min(start+ACTIVITY_PAGE_SIZE,total)} of ${total}`:'No jobs';
      const nav=document.getElementById('activity-pages');nav.replaceChildren();nav.appendChild(activityPageButton('Previous',Math.max(1,activityPage-1),activityPage===1));
      const first=Math.max(1,activityPage-2),last=Math.min(pages,first+4);for(let p=first;p<=last;p++)nav.appendChild(activityPageButton(String(p),p,false,p===activityPage));
      nav.appendChild(activityPageButton('Next',Math.min(pages,activityPage+1),activityPage===pages));
    }
    async function refreshActivityV28(){
      try{const response=await fetch(endpoint('api/status'),{cache:'no-store'});if(!response.ok)throw new Error(await response.text());const data=await response.json();activityJobs=Array.isArray(data.jobs)?data.jobs:[];renderActivityLive(data.activity||{});renderActivityHistory()}catch(error){console.warn('Live activity refresh failed',error)}
    }
    refreshActivityV28();setInterval(refreshActivityV28,2000);
    </script>
    '''
    page = page.replace('</body>', js + '</body>', 1)
    return page


_drop_route("/", "GET")


@app.get("/", response_class=HTMLResponse)
def dashboard():
    products = core.db.list_products()
    jobs = core.db.list_jobs(5000)
    page = v2.render_dashboard(
        products,
        jobs,
        core.db.get_credential("ebay") is not None,
        core.db.get_credential("etsy") is not None,
        core.db.get_credential("shopify") is not None,
        core.db.get_credential("tiktok") is not None,
    )
    return HTMLResponse(_upgrade_page(page))
