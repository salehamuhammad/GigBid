"""Runs (trace viewer + SSE), analytics and system health."""
from __future__ import annotations

import statistics
import time

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select

from agent.mcp_client import ToolBox
from agent.settings import get_settings
from agent.tracing import public_trace_url
from apps.api.auth.security import CurrentUser, get_profile
from apps.api.db import Job, Proposal, Run, RunEvent, User, kv_get, session
from apps.api.schemas import Analytics, Health, RunDetail, RunEventOut, RunOut
from apps.api.streaming import run_event_stream
from mcp_servers.common import AuditLog

router = APIRouter(prefix="/api", tags=["insight"])


def _run(r: Run) -> dict:
    return dict(id=r.id, kind=r.kind, ref=r.ref, status=r.status, trace_id=r.trace_id, tokens=r.tokens, cost_usd=r.cost_usd, latency_ms=r.latency_ms, started_at=r.started_at, ended_at=r.ended_at)


@router.get("/runs", response_model=list[RunOut])
def runs(ref: str | None = None, limit: int = 50, user: User = CurrentUser):
    with session() as s:
        q = select(Run).where(Run.user_id == user.id)
        if ref: q = q.where(Run.ref == ref)
        return [RunOut(**_run(r)) for r in s.scalars(q.order_by(Run.started_at.desc()).limit(min(limit, 200)))]


@router.get("/runs/{run_id}", response_model=RunDetail)
def run_detail(run_id: str, share: bool = False, user: User = CurrentUser):
    """One agent run: node-by-node events with tokens, cost and latency, and every tool call."""
    with session() as s:
        r = s.get(Run, run_id)
        if not r or r.user_id != user.id: raise HTTPException(404, "Run not found")
        ev = list(s.scalars(select(RunEvent).where(RunEvent.run_id == run_id).order_by(RunEvent.id)))
        job = s.scalars(select(Job).where(Job.user_id == user.id, Job.job_id == r.ref)).first() if r.kind == "bid" else None
        nodes = [{"node": e.node, "ms": e.payload.get("ms"), "tokens": e.payload.get("tokens"), "cost_usd": e.payload.get("cost_usd"), "summary": e.payload.get("summary")} for e in ev if e.type == "node_end"]
        calls = [c for c in ((job.analysis or {}).get("trace", []) if job else []) if c.get("trace_id") == r.trace_id]
        return RunDetail(**_run(r), langsmith_url=public_trace_url(r.langsmith_run_id) if share and r.langsmith_run_id else None,
                         events=[RunEventOut(id=e.id, ts=e.ts, node=e.node, type=e.type, payload=e.payload) for e in ev], nodes=nodes, tool_calls=calls)


@router.get("/runs/{run_id}/stream")
async def run_stream(run_id: str, after: int = 0, user: User = CurrentUser):
    with session() as s:
        r = s.get(Run, run_id)
        if not r or r.user_id != user.id: raise HTTPException(404, "Run not found")
    return StreamingResponse(run_event_stream(run_id, user.id, after), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/analytics", response_model=Analytics)
def analytics(user: User = CurrentUser):
    """Funnel, reply rate, Connects spent per reply, cost and latency per run."""
    b = get_settings().cfg["budgets"]["declared"]
    with session() as s:
        props = list(s.scalars(select(Proposal).where(Proposal.user_id == user.id)))
        rs = list(s.scalars(select(Run).where(Run.user_id == user.id, Run.kind == "bid")))
        jobs_n = s.scalar(select(func.count()).select_from(Job).where(Job.user_id == user.id)) or 0
        analysed = s.scalar(select(func.count()).select_from(Job).where(Job.user_id == user.id, Job.fit.is_not(None))) or 0
    sent = [p for p in props if p.stage not in ("drafted", "rejected")]
    replied = [p for p in sent if p.stage in ("replied", "interview", "hired")]
    hired = [p for p in sent if p.stage == "hired"]
    connects = sum(p.connects for p in sent)
    funnel = {"scouted": jobs_n, "analysed": analysed, "drafted": len(props), "submitted": len(sent), "viewed": sum(p.stage in ("viewed", "replied", "interview", "hired") for p in sent),
              "replied": len(replied), "interview": sum(p.stage in ("interview", "hired") for p in sent), "hired": len(hired)}
    def group(keyfn):
        out = {}
        for p in sent:
            g = out.setdefault(keyfn(p), {"sent": 0, "replied": 0, "connects": 0}); g["sent"] += 1; g["connects"] += p.connects; g["replied"] += p in replied
        return [{"name": k, **v, "reply_rate": round(v["replied"] / v["sent"], 3)} for k, v in sorted(out.items())]
    lat = sorted(r.latency_ms for r in rs if r.latency_ms) or [0]
    cost = sum(r.cost_usd for r in rs)
    arms = group(lambda p: p.strategy)
    return Analytics(funnel=funnel, reply_rate=round(len(replied) / len(sent), 3) if sent else 0.0, hire_rate=round(len(hired) / len(sent), 3) if sent else 0.0, connects_spent=connects,
                     replies_per_10_connects=round(10 * len(replied) / connects, 2) if connects else 0.0, by_category=group(lambda p: p.category), by_strategy=arms, cost_usd=round(cost, 4),
                     cost_per_job_usd=round(cost / analysed, 5) if analysed else 0.0, tokens=sum(r.tokens for r in rs), latency_ms_p50=int(statistics.median(lat)),
                     latency_ms_p95=int(lat[min(len(lat) - 1, int(0.95 * len(lat)))]), runs=len(rs), budgets=b, experiment={"arms": arms} if len(arms) > 1 else None)


_health_cache: dict = {"at": 0, "value": None}


@router.get("/system/health", response_model=Health)
async def health(user: User = CurrentUser):
    """Drives the degraded-mode banner: which MCP servers answer, is the marketplace reachable, how many jobs are queued."""
    s_ = get_settings()
    with session() as s:
        owner = get_profile(s, user.id).owner
        market = kv_get(s, "_system", "marketplace", {"ok": True, "detail": "", "at": 0})
        queued = s.scalar(select(func.count()).select_from(Job).where(Job.user_id == user.id, Job.status == "queued")) or 0
    if time.time() - _health_cache["at"] > 10:
        tb = ToolBox(user.id, owner)
        servers = await tb.health()
        if servers.get("marketplace"):
            try: await tb.call("pricing", "marketplace.get_policy", {}); market = {"ok": True, "detail": "", "at": time.time()}
            except Exception as e: market = {"ok": False, "detail": str(e)[:200], "at": time.time()}
        else: market = {"ok": False, "detail": "Marketplace MCP server unreachable", "at": time.time()}
        _health_cache.update(at=time.time(), value=(servers, market))
    servers, market = _health_cache["value"]
    ok = all(servers.values()) and market["ok"]
    return Health(status="ok" if ok else "degraded", marketplace=market, servers=servers, queued_jobs=queued, model_profile=s_.profile_name, marketplace_mode=s_.marketplace_mode,
                  worker="arq (redis)" if s_.redis_url else "in-process")


@router.get("/system/audit")
def audit(limit: int = 50, user: User = CurrentUser) -> list[dict]:
    """The caller's own slice of the Marketplace server's append-only audit log."""
    return AuditLog("marketplace").tail(min(limit, 200), user=user.id)
