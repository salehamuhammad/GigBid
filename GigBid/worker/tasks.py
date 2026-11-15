"""Long-running work (E1): scouting, bid runs, approval resumes, conversations, event polling.

Every task is idempotent, so a worker restart never double-analyses or double-submits:
  * run_bid claims the job with a conditional UPDATE (new/queued -> analysing); a second worker gets 0 rows;
  * the graph resumes from its checkpoint, not from the start;
  * every marketplace write carries an idempotency key derived from the thread id.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import time
import uuid
from datetime import datetime, timedelta, timezone

from langgraph.types import Command
from sqlalchemy import select, update

from agent.graphs.bid_graph import bid_thread_id
from agent.graphs.conversation_graph import conversation_thread_id
from agent.guardrails import mask_obj
from agent.mcp_client import ToolBox, ToolUnavailable
from agent.memory.store import Memory
from agent.nodes.scout import scout, signature
from agent.runtime import Ctx
from agent.settings import get_settings
from agent.tracing import new_trace_id, run_config
from apps.api.auth.security import get_profile
from apps.api.db import (
    Approval,
    Conversation,
    Job,
    Proposal,
    Run,
    RunEvent,
    SavedSearch,
    kv_get,
    kv_set,
    session,
)
from worker.engine import engine
from worker.queue import enqueue

log = logging.getLogger("gigbid.worker")
STAGES = ["drafted", "submitted", "viewed", "replied", "interview", "hired", "lost"]


# ------------------------------------------------------------------ helpers
def user_snapshot(user_id: str) -> tuple[dict, str]:
    with session() as s:
        p = get_profile(s, user_id)
        week = (datetime.now(timezone.utc) - timedelta(days=datetime.now(timezone.utc).weekday())).replace(hour=0, minute=0, second=0).timestamp()
        spent = sum(x.connects for x in s.scalars(select(Proposal).where(Proposal.user_id == user_id, Proposal.updated_at >= week, Proposal.stage.notin_(["drafted", "rejected"]))))
        return {**p.settings, "connects_spent_week": spent}, p.owner


def event(run_id: str, user_id: str, node: str, typ: str, payload: dict) -> None:
    with session() as s:
        s.add(RunEvent(run_id=run_id, user_id=user_id, node=node, type=typ, payload=mask_obj(payload)))


def set_market_health(ok: bool, detail: str = "") -> None:
    with session() as s:
        kv_set(s, "_system", "marketplace", {"ok": ok, "detail": detail, "at": time.time()})


async def drive(graph, inp, cfg: dict, ctx: Ctx, run_id: str) -> str:
    """Run a graph to its next stop (END or interrupt), turning the stream into run events.
    Returns the run status."""
    usage: list[dict] = []
    t0 = time.perf_counter()
    try:
        async for mode, ev in graph.astream(inp, cfg, context=ctx, stream_mode=["custom", "updates"]):
            if mode == "custom":
                event(run_id, ctx.user_id, ev.get("node", ""), ev.get("event", "info"), {k: v for k, v in ev.items() if k not in ("node", "event")})
            else:
                for name, upd in ev.items():
                    if name == "__interrupt__":
                        event(run_id, ctx.user_id, "approval", "interrupt", {"message": "Waiting for your approval"})
                    elif isinstance(upd, dict):
                        usage += upd.get("usage", [])
                        if upd.get("errors"): event(run_id, ctx.user_id, name, "error", {"errors": upd["errors"]})
        snap = await graph.aget_state(cfg)
        status = "waiting_approval" if snap.next else "done"
        set_market_health(True)
    except ToolUnavailable as e:
        status = "queued"
        if e.server == "marketplace" and "rate limited" not in str(e): set_market_health(False, str(e))
        event(run_id, ctx.user_id, e.server, "degraded", {"message": f"{e.server} server unavailable; the job is queued and will resume automatically", "detail": str(e)[:200]})
    except Exception as e:  # noqa: BLE001
        log.exception("run %s failed", run_id)
        status = "failed"
        event(run_id, ctx.user_id, "", "error", {"errors": [f"{type(e).__name__}: {str(e)[:300]}"]})
    with session() as s:
        r = s.get(Run, run_id)
        r.status, r.ended_at, r.latency_ms = status, time.time(), int((time.perf_counter() - t0) * 1000)
        r.tokens = sum(u.get("input_tokens", 0) + u.get("output_tokens", 0) for u in usage)
        r.cost_usd = round(sum(u.get("cost_usd", 0) for u in usage), 6)
    event(run_id, ctx.user_id, "", "end", {"status": status})
    return status


def _new_run(user_id: str, kind: str, ref: str, thread_id: str, trace_id: str | None) -> Run:
    with session() as s:
        r = Run(user_id=user_id, kind=kind, ref=ref, thread_id=thread_id, trace_id=trace_id or new_trace_id(), langsmith_run_id=str(uuid.uuid4()))
        s.add(r); s.flush()
        return r


def _upsert_approval(s, user_id: str, kind: str, thread_id: str, ref: str, payload: dict, n: int) -> None:
    aid = "ap-" + hashlib.sha1(f"{thread_id}#{n}".encode()).hexdigest()[:20]      # URL-safe, stable per (thread, round)
    for old in s.scalars(select(Approval).where(Approval.thread_id == thread_id, Approval.status == "pending", Approval.id != aid)): old.status = "superseded"
    ap = s.get(Approval, aid)
    if ap is None: s.add(Approval(id=aid, user_id=user_id, kind=kind, thread_id=thread_id, ref=ref, payload=payload))
    elif ap.status == "pending": ap.payload = payload


# ------------------------------------------------------------------ bid graph
async def run_bid(user_id: str, job_id: str, trace_id: str | None = None, force: bool = False) -> str | None:
    eng = await engine()
    tid = bid_thread_id(user_id, job_id)
    with session() as s:
        allowed = ["new", "queued"] + (["skipped", "watch", "rejected", "blocked", "needs_attention", "dead_letter", "filtered"] if force else [])
        claimed = s.execute(update(Job).where(Job.user_id == user_id, Job.job_id == job_id, Job.status.in_(allowed)).values(status="analysing", updated_at=time.time())).rowcount
        if not claimed: return None                      # someone else has it, or it is already done
        job = s.scalars(select(Job).where(Job.user_id == user_id, Job.job_id == job_id)).one()
        payload = dict(job.payload)
    user, owner = user_snapshot(user_id)
    run = _new_run(user_id, "bid", job_id, tid, trace_id)
    with session() as s:
        s.execute(update(Job).where(Job.user_id == user_id, Job.job_id == job_id).values(run_id=run.id))
    cfg = run_config(tid, run.trace_id, user_id, "bid", job_id, run.langsmith_run_id)
    snap = await eng.bid.aget_state(cfg)
    if force and snap.values:
        await eng.saver.adelete_thread(tid); snap = None
    resume_from_checkpoint = bool(snap and snap.next and not (snap.tasks and snap.tasks[0].interrupts))
    ctx = Ctx(user_id=user_id, owner=owner, trace_id=run.trace_id, run_id=run.id, tools=ToolBox(user_id, owner, run.trace_id))
    await drive(eng.bid, None if resume_from_checkpoint else {"job": payload, "user": user}, cfg, ctx, run.id)
    await sync_bid(user_id, job_id, run.id)
    return run.id


async def sync_bid(user_id: str, job_id: str, run_id: str | None = None) -> None:
    """Project the graph's state into the app tables the UI reads (jobs, proposals, approvals)."""
    eng = await engine()
    tid = bid_thread_id(user_id, job_id)
    snap = await eng.bid.aget_state({"configurable": {"thread_id": tid}})
    v = snap.values or {}
    a = v.get("analyses", {})
    waiting = bool(snap.next and snap.tasks and snap.tasks[0].interrupts)
    with session() as s:
        job = s.scalars(select(Job).where(Job.user_id == user_id, Job.job_id == job_id)).one()
        run = s.get(Run, run_id) if run_id else None
        if run and run.status == "queued": job.status, job.note = "queued", "Marketplace unavailable - queued, will resume automatically"
        elif run and run.status == "failed": job.status, job.note = "needs_attention", "Run failed; see the run trace"
        elif waiting: job.status, job.note = "awaiting_approval", ""
        else:
            st = v.get("status") or "new"
            job.status = st if st in ("submitted", "awaiting_upwork", "rejected", "blocked", "skipped", "watch", "needs_attention", "dead_letter") else job.status if not v else "needs_attention"
            job.note = (v.get("compliance") or {}).get("reason", "") if st == "blocked" else "; ".join(v.get("errors", [])[-2:]) if st in ("needs_attention", "dead_letter") else ""
        fit, risk, dec, price = a.get("fit") or {}, a.get("risk") or {}, v.get("decision") or {}, v.get("price") or {}
        job.fit, job.risk, job.action = fit.get("score"), risk.get("score"), dec.get("action")
        job.price, job.connects_cost = price.get("bid_amount"), price.get("connects_cost") or (job.payload.get("connects") or {}).get("total")
        usage = v.get("usage", [])
        job.analysis = {"job_spec": a.get("job_spec"), "risk": risk, "fit": fit, "client": a.get("client"), "decision": dec, "price": price, "verification": v.get("verification"),
                        "critiques": v.get("critiques", []), "compliance": v.get("compliance"), "errors": v.get("errors", []), "injection": (v.get("job") or {}).get("injection"),
                        "trace": v.get("trace", [])[-60:], "usage": usage, "tokens": v.get("tokens", 0), "steps": v.get("steps", 0), "outcome": v.get("outcome"),
                        "description_clean": (v.get("job") or {}).get("description")}
        job.updated_at = time.time()
        draft = v.get("draft")
        if draft:
            p = s.scalars(select(Proposal).where(Proposal.user_id == user_id, Proposal.job_id == job_id)).first()
            if p is None:
                p = Proposal(user_id=user_id, job_id=job_id, title=job.title, category=job.category); s.add(p)
            p.draft, p.bid, p.strategy, p.updated_at = draft, price.get("bid_amount"), draft.get("strategy", "evidence_first"), time.time()
            out = v.get("outcome") or {}
            if v.get("status") == "submitted" and p.stage == "drafted":
                p.stage, p.marketplace_proposal_id, p.conversation_id, p.connects = "submitted", out.get("proposal_id"), out.get("thread_id"), out.get("connects_spent", 0)
                await Memory(eng.store, user_id).record_outcome({"category": job.category, "strategy": p.strategy, "outcome": "sent"})
            elif v.get("status") == "rejected":
                p.stage, p.reject_reason = "rejected", (v.get("approval") or {}).get("reason") or ""
        if waiting:
            _upsert_approval(s, user_id, "proposal", tid, job_id, snap.tasks[0].interrupts[0].value, len(v.get("approvals", [])))


async def _resume(kind: str, user_id: str, approval_id: str, decision: dict, trace_id: str | None = None) -> str | None:
    eng = await engine()
    graph = eng.bid if kind == "bid" else eng.conv
    with session() as s:
        ap = s.get(Approval, approval_id)
        if ap is None or ap.user_id != user_id: return None
        if ap.status == "pending": ap.status, ap.decision, ap.decided_at = "processing", decision, time.time()
        elif ap.status != "processing": return None       # already handled: a double click or a redelivered task does nothing
        tid, ref, decision = ap.thread_id, ap.ref, ap.decision
    run = _new_run(user_id, kind, ref, tid, trace_id)
    cfg = run_config(tid, run.trace_id, user_id, kind, ref, run.langsmith_run_id)
    snap = await graph.aget_state(cfg)
    user, owner = user_snapshot(user_id)
    ctx = Ctx(user_id=user_id, owner=owner, trace_id=run.trace_id, run_id=run.id, tools=ToolBox(user_id, owner, run.trace_id))
    if snap.next:
        # Still at the interrupt -> deliver the decision. Already past it (crashed after approval,
        # before submit) -> just continue from the checkpoint; the idempotency key prevents a double submit.
        at_gate = bool(snap.tasks and snap.tasks[0].interrupts)
        status = await drive(graph, Command(resume=decision) if at_gate else None, cfg, ctx, run.id)
    else:
        status = "done"
        with session() as s: s.get(Run, run.id).status = "done"
    # Keep the approval recoverable until the UI-facing rows have been committed.
    if kind == "bid":
        await sync_bid(user_id, ref, run.id)
    else:
        await sync_conversation(user_id, ref)
    if status in ("done", "waiting_approval"):
        with session() as s:
            s.get(Approval, approval_id).status = {"approve": "approved", "reject": "rejected", "edit": "edited", "regenerate": "edited"}[decision["action"]]
    return run.id


async def resume_bid(user_id: str, approval_id: str, decision: dict, trace_id: str | None = None) -> str | None:
    return await _resume("bid", user_id, approval_id, decision, trace_id)


# ------------------------------------------------------------------ conversation graph
async def run_conversation(user_id: str, conversation_id: str, trace_id: str | None = None) -> str | None:
    eng = await engine()
    tid = conversation_thread_id(user_id, conversation_id)
    cfg0 = {"configurable": {"thread_id": tid}}
    snap = await eng.conv.aget_state(cfg0)
    if snap.next: return None                               # a reply is already waiting for approval
    user, owner = user_snapshot(user_id)
    with session() as s:
        p = s.scalars(select(Proposal).where(Proposal.user_id == user_id, Proposal.conversation_id == conversation_id)).first()
        job = {"bid_amount": p.bid, "job_id": p.job_id} if p else {}
    run = _new_run(user_id, "conversation", conversation_id, tid, trace_id)
    cfg = run_config(tid, run.trace_id, user_id, "conversation", conversation_id, run.langsmith_run_id)
    ctx = Ctx(user_id=user_id, owner=owner, trace_id=run.trace_id, run_id=run.id, tools=ToolBox(user_id, owner, run.trace_id))
    fresh = {"thread_id": conversation_id, "user": user, "job": job, "approval": {}, "reply": {}, "slots": [], "intent": {}, "outcome": {}, "status": "reading", "steps": None, "tokens": None}
    await drive(eng.conv, fresh, cfg, ctx, run.id)
    await sync_conversation(user_id, conversation_id)
    return run.id


async def sync_conversation(user_id: str, conversation_id: str) -> None:
    eng = await engine()
    tid = conversation_thread_id(user_id, conversation_id)
    snap = await eng.conv.aget_state({"configurable": {"thread_id": tid}})
    v = snap.values or {}
    waiting = bool(snap.next and snap.tasks and snap.tasks[0].interrupts)
    with session() as s:
        c = s.scalars(select(Conversation).where(Conversation.user_id == user_id, Conversation.conversation_id == conversation_id)).first()
        if c is None:
            c = Conversation(user_id=user_id, conversation_id=conversation_id); s.add(c)
        if v.get("messages"): c.messages = v["messages"]
        if (v.get("outcome") or {}).get("sent_at") and v.get("reply"):
            if not c.messages or c.messages[-1].get("from") != "freelancer":
                c.messages = [*c.messages, {"id": v["outcome"].get("message_id") or f"local-{int(time.time())}", "from": "freelancer", "text": v["reply"]["text"], "at": v["outcome"]["sent_at"]}]
        c.intent = (v.get("intent") or {}).get("intent", c.intent or "")
        c.job_id = (v.get("job") or {}).get("job_id") or c.job_id
        status = v.get("status")
        if waiting:
            c.status = "awaiting_approval"
        elif status == "awaiting_upwork":
            c.status = "awaiting_upwork"
        elif c.intent == "scam_signal" and status != "sent":
            c.status = "flagged"
        else:
            c.status = {"sent": "replied", "rejected": "open", "idle": "open", "blocked": "flagged"}.get(status, "open")
        c.updated_at = time.time()
        if waiting:
            _upsert_approval(s, user_id, "message", tid, conversation_id, snap.tasks[0].interrupts[0].value, int(time.time()))


async def resume_conversation(user_id: str, approval_id: str, decision: dict, trace_id: str | None = None) -> str | None:
    return await _resume("conversation", user_id, approval_id, decision, trace_id)


# ------------------------------------------------------------------ scouting + events
_scout_locks: dict[str, "asyncio.Lock"] = {}


async def scout_user(user_id: str, force: bool = False, max_new: int | None = None) -> int:
    lock = _scout_locks.setdefault(user_id, asyncio.Lock())
    if lock.locked(): return 0                                           # one scouting pass per user at a time
    async with lock:
        return await _scout_user(user_id, force, max_new)


async def _scout_user(user_id: str, force: bool = False, max_new: int | None = None) -> int:
    """Run the user's saved searches that are due; insert new jobs (unique per user) and queue their analysis."""
    user, owner = user_snapshot(user_id)
    with session() as s:
        searches = list(s.scalars(select(SavedSearch).where(SavedSearch.user_id == user_id, SavedSearch.enabled == 1)))
        min_iv = get_settings().cfg["marketplace"]["scout_interval_minutes"][get_settings().marketplace_mode]
        due = [x for x in searches if force or time.time() - x.last_run_at >= max(x.interval_minutes, min_iv) * 60]
        seen = {j.job_id for j in s.scalars(select(Job).where(Job.user_id == user_id))}
        sigs = {j.signature: j.job_id for j in s.scalars(select(Job).where(Job.user_id == user_id)) if j.signature}
    if not due: return 0
    tools, log_ = ToolBox(user_id, owner, new_trace_id()), []
    try:
        jobs = await scout(tools, [{"query": x.query, "category": x.category} for x in due], seen, sigs, log=log_, max_new=max_new or get_settings().cfg["marketplace"]["scout_max_new_per_run"])
        set_market_health(True)
    except ToolUnavailable as e:
        if "rate limited" not in str(e): set_market_health(False, str(e))
        return 0
    n = 0
    with session() as s:
        for x in s.scalars(select(SavedSearch).where(SavedSearch.id.in_([d.id for d in due]))): x.last_run_at = time.time()
        existing = {j.job_id for j in s.scalars(select(Job).where(Job.user_id == user_id, Job.job_id.in_([x["job_id"] for x in jobs])))}
        jobs = [x for x in jobs if x["job_id"] not in existing]       # another scouting pass got there first
        for job in jobs:
            b = job.get("budget") or {}
            filtered = (user.get("categories") and job.get("category") not in user["categories"]) or (b.get("type") == "fixed" and (b.get("max") or 0) < user.get("min_budget", 0))
            status = "skipped" if job.get("duplicate_of") else "filtered" if filtered else "new"
            s.add(Job(user_id=user_id, job_id=job["job_id"], title=job.get("title", ""), category=job.get("category", ""), signature=job.get("signature", signature(job)), payload=job, status=status,
                      action="skip" if status != "new" else None, connects_cost=(job.get("connects") or {}).get("total"),
                      note=f"Duplicate of {job['duplicate_of']}" if job.get("duplicate_of") else "Outside your saved filters" if filtered else ""))
            n += status == "new"
    for job in jobs:
        if not job.get("duplicate_of"): await enqueue("run_bid", user_id, job["job_id"], key=f"bid:{user_id}:{job['job_id']}")
    return n


async def poll_events(user_id: str) -> int:
    """Marketplace events -> pipeline board, outcome memory, and new client messages -> conversation graph."""
    eng = await engine()
    _, owner = user_snapshot(user_id)
    with session() as s: cursor = kv_get(s, user_id, "event_cursor", {"since": 0})["since"]
    try:
        res = await ToolBox(user_id, owner, new_trace_id()).call("liaison", "marketplace.list_events", {"since": cursor})
        set_market_health(True)
    except ToolUnavailable as e:
        set_market_health(False, str(e)); return 0
    to_run = []
    for e in res.get("events", []):
        with session() as s:
            if e["type"] in STAGES:
                p = s.scalars(select(Proposal).where(Proposal.user_id == user_id, Proposal.marketplace_proposal_id == e.get("proposal_id"))).first()
                if p and (e["type"] == "lost" or STAGES.index(e["type"]) > STAGES.index(p.stage if p.stage in STAGES else "drafted")):
                    already = p.stage in ("replied", "interview", "hired")
                    p.stage, p.updated_at = e["type"], time.time()
                    if e["type"] in ("replied", "interview", "hired"):
                        await Memory(eng.store, user_id).record_outcome({"category": p.category, "strategy": p.strategy, "outcome": e["type"], "already_replied": already})
            elif e["type"] == "client_message":
                c = s.scalars(select(Conversation).where(Conversation.user_id == user_id, Conversation.conversation_id == e["thread_id"])).first()
                if c is None:
                    p = s.scalars(select(Proposal).where(Proposal.user_id == user_id, Proposal.conversation_id == e["thread_id"])).first()
                    c = Conversation(user_id=user_id, conversation_id=e["thread_id"], job_id=e.get("job_id", ""), title=p.title if p else e.get("job_id", ""), messages=[]); s.add(c)
                if not any(m.get("id") == e["id"] for m in c.messages):
                    c.messages = [*c.messages, {"id": e["id"], "from": "client", "text": e["text"], "at": e["at"]}]
                c.status, c.updated_at = "needs_reply", time.time()
                to_run.append(e["thread_id"])
    with session() as s: kv_set(s, user_id, "event_cursor", {"since": res.get("cursor", cursor)})
    for conv in dict.fromkeys(to_run):
        await enqueue("run_conversation", user_id, conv, key=f"conv:{user_id}:{conv}:{res.get('cursor')}")
    return len(res.get("events", []))


async def retry_queued(user_id: str) -> int:
    """Degraded-mode recovery: jobs parked while a server was down are resumed from their checkpoint."""
    with session() as s:
        ids = [j.job_id for j in s.scalars(select(Job).where(Job.user_id == user_id, Job.status == "queued"))]
        stuck = [(a.id, a.kind, a.decision) for a in s.scalars(select(Approval).where(Approval.user_id == user_id, Approval.status == "processing", Approval.decided_at < time.time() - 20))]
    for jid in ids: await enqueue("run_bid", user_id, jid, key=f"bid:{user_id}:{jid}")
    for aid, kind, decision in stuck:
        await enqueue("resume_bid" if kind == "proposal" else "resume_conversation", user_id, aid, decision, key=f"resume:{aid}")
    return len(ids) + len(stuck)


async def recover() -> None:
    """After a crash/restart: nothing stays 'analysing' or 'running' forever."""
    with session() as s:
        s.execute(update(Job).where(Job.status == "analysing").values(status="queued", note="Recovered after restart"))
        s.execute(update(Run).where(Run.status == "running").values(status="failed", summary="interrupted by restart", ended_at=time.time()))
        s.execute(update(Approval).where(Approval.status == "processing").values(decided_at=0))


async def tick() -> None:
    """Scheduler heartbeat: per onboarded user, scout what is due, pull events, resume queued work."""
    from apps.api.db import Profile
    with session() as s:
        users = [p.user_id for p in s.scalars(select(Profile)) if p.settings.get("onboarded")]
    for u in users:
        try:
            await retry_queued(u); await scout_user(u); await poll_events(u)
        except Exception:  # noqa: BLE001
            log.exception("tick failed for %s", u)
