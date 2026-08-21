from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from fastapi import Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select

from .db import SessionLocal
from .main import app, current_context, dashboard as base_dashboard
from .models import SyncJob
from .sync_routes import router as sync_router
from .sync_routes import run_import, update_job

app.include_router(sync_router)

# Keep the cloud dashboard from main.py, but add a direct Product workspace
# navigation item without changing any Home Assistant UI/source files.
app.router.routes[:] = [
    route
    for route in app.router.routes
    if not (getattr(route, "path", None) == "/dashboard" and "GET" in getattr(route, "methods", set()))
]


@app.get("/dashboard", response_class=HTMLResponse)
def cloud_dashboard(request: Request):
    if not current_context(request):
        return RedirectResponse("/login", status_code=303)
    response = base_dashboard(request)
    if not isinstance(response, HTMLResponse):
        return response
    page = response.body.decode("utf-8")
    page = page.replace(
        '<div class="nav"><a href="/dashboard">Dashboard</a>',
        '<div class="nav"><a href="/dashboard">Dashboard</a><a href="/catalog">Product workspace</a>',
        1,
    )
    return HTMLResponse(page, status_code=response.status_code)


_previous_lifespan = app.router.lifespan_context
_recovery_tasks: set[asyncio.Task] = set()


@asynccontextmanager
async def recovery_lifespan(application):
    async with _previous_lifespan(application):
        with SessionLocal() as db:
            stale = db.scalars(
                select(SyncJob).where(SyncJob.status.in_(["running", "queued"]))
            ).all()
            stale_jobs = [
                {
                    "id": job.id,
                    "workspace_id": job.workspace_id,
                    "kind": job.kind,
                }
                for job in stale
            ]

        for job in stale_jobs:
            kind = str(job["kind"] or "")
            if kind.endswith("_import"):
                provider = kind.removesuffix("_import")
                if provider in {"shopify", "etsy", "ebay"}:
                    update_job(
                        job["id"],
                        status="queued",
                        progress="0/0",
                        message="Recovered after restart — safely restarting this import from the beginning.",
                    )
                    task = asyncio.create_task(
                        run_import(job["id"], job["workspace_id"], provider),
                        name=f"shopsync-cloud-recover-{provider}-{job['id']}",
                    )
                    _recovery_tasks.add(task)
                    task.add_done_callback(_recovery_tasks.discard)
                    continue

            # Never blindly retry marketplace writes after a restart. A remote
            # marketplace may have accepted the request before the connection
            # dropped, which could create a duplicate if retried automatically.
            update_job(
                job["id"],
                status="failed",
                message="Interrupted by a Shop Sync restart. Review this export before retrying so a listing is not duplicated.",
            )
        yield


app.router.lifespan_context = recovery_lifespan
