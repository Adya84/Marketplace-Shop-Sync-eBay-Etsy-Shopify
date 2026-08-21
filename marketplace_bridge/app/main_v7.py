from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from . import main as core
from . import main_v6 as v6

app = v6.app
app.version = "0.0.32"

_previous_lifespan = app.router.lifespan_context
_recovery_tasks: set[asyncio.Task] = set()


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
