from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from fastapi import Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select

from . import runtime_patches  # noqa: F401 - installs cloud-only import fixes
from . import sync_routes
from .db import SessionLocal
from .main import app, current_context
from .models import SyncJob
from .original_ui import render_control_centre, router as original_ui_router
from .sync_routes import router as sync_router

app.include_router(sync_router)
app.include_router(original_ui_router)

# The hosted edition keeps account/login handling from cloud/main.py, but once
# signed in it presents the same single Shop Sync control-centre layout as the
# Home Assistant edition rather than a separate dashboard/catalogue design.
app.router.routes[:] = [
    route
    for route in app.router.routes
    if not (
        getattr(route, "path", None) in {"/dashboard", "/catalog"}
        and "GET" in (getattr(route, "methods", set()) or set())
    )
]


@app.get("/dashboard", response_class=HTMLResponse)
def cloud_dashboard(request: Request):
    if not current_context(request):
        return RedirectResponse("/login", status_code=303)
    return render_control_centre(request)


@app.get("/catalog", response_class=HTMLResponse)
def cloud_catalog(request: Request):
    if not current_context(request):
        return RedirectResponse("/login", status_code=303)
    return render_control_centre(request)


_previous_lifespan = app.router.lifespan_context
_recovery_tasks: set[asyncio.Task] = set()


@asynccontextmanager
async def recovery_lifespan(application):
    async with _previous_lifespan(application):
        with SessionLocal() as db:
            stale = db.scalars(select(SyncJob).where(SyncJob.status.in_(["running", "queued"]))).all()
            stale_jobs = [
                {"id": job.id, "workspace_id": job.workspace_id, "kind": job.kind}
                for job in stale
            ]

        for job in stale_jobs:
            kind = str(job["kind"] or "")
            if kind.endswith("_import"):
                provider = kind.removesuffix("_import")
                if provider in {"shopify", "etsy", "ebay"}:
                    sync_routes.update_job(
                        job["id"],
                        status="queued",
                        progress="0/0",
                        message="Recovered after Shop Sync restart — restarting this import safely from the beginning.",
                    )
                    task = asyncio.create_task(
                        sync_routes.run_import(job["id"], job["workspace_id"], provider),
                        name=f"shopsync-cloud-recover-{provider}-{job['id']}",
                    )
                    _recovery_tasks.add(task)
                    task.add_done_callback(_recovery_tasks.discard)
                    continue

            sync_routes.update_job(
                job["id"],
                status="failed",
                message="Interrupted by a Shop Sync restart. Review this export before retrying so a listing is not duplicated.",
            )
        yield


app.router.lifespan_context = recovery_lifespan
