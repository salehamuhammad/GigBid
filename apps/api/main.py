"""GigBid API (FastAPI). Run:  uvicorn apps.api.main:app --port 8000

No agent ever runs inside a request handler: handlers enqueue tasks (worker/queue.py) and the UI
follows progress over SSE. Without REDIS_URL the queue runs in this process (local mode); set
GIGBID_EMBED_GIGSIM=1 to also mount the simulator at /gigsim for single-container deployment.
"""
from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from agent.guardrails import install_log_masking
from agent.settings import get_settings
from agent.tracing import new_trace_id
from apps.api.db import engine as db_engine
from apps.api.routers import auth, insight, jobs, profile, workflow
from worker import tasks
from worker.engine import ENGINE

log = logging.getLogger("gigbid.api")


async def _scheduler():
    while True:
        await asyncio.sleep(float(os.getenv("GIGBID_TICK_SECONDS", "20")))
        try: await tasks.tick()
        except Exception: log.exception("tick failed")  # noqa: BLE001


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.basicConfig(level=logging.INFO); install_log_masking()
    db_engine(); await ENGINE.start()
    bg = None
    if not get_settings().redis_url and os.getenv("GIGBID_NO_SCHEDULER") != "1":      # local mode: this process is also the worker
        await tasks.recover()
        bg = asyncio.create_task(_scheduler())
    yield
    if bg: bg.cancel()
    await ENGINE.stop()


app = FastAPI(title="GigBid API", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:3000").split(","), allow_methods=["*"], allow_headers=["*"], expose_headers=["X-Trace-Id"])


@app.middleware("http")
async def trace_middleware(request: Request, call_next):
    """One trace id from the UI through the API, the graph, the MCP servers and the audit log."""
    request.state.trace_id = request.headers.get("x-trace-id") or new_trace_id()
    response = await call_next(request)
    response.headers["X-Trace-Id"] = request.state.trace_id
    return response


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    log.exception("unhandled error")
    return JSONResponse({"detail": "Internal error", "trace_id": getattr(request.state, "trace_id", "")}, status_code=500)


@app.get("/api/healthz", tags=["system"])
def healthz() -> dict: return {"status": "ok"}


for r in (auth.router, profile.router, jobs.router, workflow.router, insight.router):
    app.include_router(r)

if os.getenv("GIGBID_EMBED_GIGSIM") == "1":
    import httpx

    from gigsim.app import app as gigsim_app
    from mcp_servers.marketplace.adapters import gigsim as _adapter
    app.mount("/gigsim", gigsim_app)
    _adapter.set_transport(httpx.ASGITransport(app=gigsim_app))      # the adapter talks to the mounted simulator in-process
