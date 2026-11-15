from __future__ import annotations

import time

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select

from apps.api.auth.security import CurrentUser
from apps.api.db import Approval, Job, Proposal, SavedSearch, User, session
from apps.api.schemas import Accepted, JobDetail, JobSummary
from worker.queue import enqueue

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


def summary(j: Job) -> dict:
    a = j.analysis or {}
    return dict(job_id=j.job_id, title=j.title, category=j.category, status=j.status, fit=j.fit, risk=j.risk, action=j.action, price=j.price, connects_cost=j.connects_cost,
                budget=j.payload.get("budget") or {}, posted_at=j.payload.get("posted_at"), note=j.note or "", flags=[f["code"] for f in (a.get("risk") or {}).get("flags", [])],
                reasons=(a.get("decision") or {}).get("reasons", []), run_id=j.run_id, updated_at=j.updated_at)


@router.get("", response_model=list[JobSummary])
def inbox(status: str | None = None, sort: str = "fit", user: User = CurrentUser):
    """Job inbox: fit score, risk flags and a recommended action per job; filterable and sortable."""
    with session() as s:
        q = select(Job).where(Job.user_id == user.id)
        if status: q = q.where(Job.status.in_(status.split(",")))
        rows = [JobSummary(**summary(j)) for j in s.scalars(q)]
    key = {"fit": lambda r: -(r.fit or -1), "risk": lambda r: -(r.risk or 0), "recent": lambda r: -r.updated_at, "budget": lambda r: -((r.budget or {}).get("max") or 0)}.get(sort, lambda r: -r.updated_at)
    return sorted(rows, key=key)


@router.post("/scout", response_model=Accepted)
async def scout_now(user: User = CurrentUser):
    with session() as s:
        enabled = s.scalar(select(SavedSearch.id).where(
            SavedSearch.user_id == user.id, SavedSearch.enabled == 1
        ).limit(1))
    if enabled is None:
        return Accepted(detail="Enable or add a saved search in Settings before scouting.")
    await enqueue("scout_user", user.id, True, key=f"scout:{user.id}:{int(time.time())}")
    return Accepted(detail="Scouting now. New jobs appear here as they are analysed.")


@router.get("/{job_id}", response_model=JobDetail)
def detail(job_id: str, user: User = CurrentUser):
    with session() as s:
        j = s.scalars(select(Job).where(Job.user_id == user.id, Job.job_id == job_id)).first()
        if not j: raise HTTPException(404, "Job not found")
        p = s.scalars(select(Proposal).where(Proposal.user_id == user.id, Proposal.job_id == job_id)).first()
        ap = s.scalars(select(Approval).where(Approval.user_id == user.id, Approval.ref == job_id, Approval.kind == "proposal", Approval.status == "pending")).first()
        return JobDetail(**summary(j), description=(j.analysis or {}).get("description_clean") or j.payload.get("description", ""), screening_questions=j.payload.get("screening_questions", []),
                         client_id=j.payload.get("client_id"), analysis=j.analysis or {}, approval_id=ap.id if ap else None,
                         proposal={"stage": p.stage, "draft": p.draft, "bid": p.bid, "connects": p.connects, "conversation_id": p.conversation_id} if p else None)


@router.post("/{job_id}/analyze", response_model=Accepted)
async def analyze(job_id: str, request: Request, user: User = CurrentUser):
    """(Re)run the bid graph for this job from a clean thread."""
    with session() as s:
        j = s.scalars(select(Job).where(Job.user_id == user.id, Job.job_id == job_id)).first()
        if not j: raise HTTPException(404, "Job not found")
        if j.status in ("analysing", "awaiting_approval", "submitted"): raise HTTPException(409, f"Job is {j.status}")
    await enqueue("run_bid", user.id, job_id, request.state.trace_id, True, key=f"bid:{user.id}:{job_id}:{int(time.time())}")
    return Accepted(detail="Analysis started")


@router.post("/{job_id}/skip", response_model=Accepted)
def skip(job_id: str, user: User = CurrentUser):
    with session() as s:
        j = s.scalars(select(Job).where(Job.user_id == user.id, Job.job_id == job_id)).first()
        if not j: raise HTTPException(404, "Job not found")
        if j.status == "submitted": raise HTTPException(409, "Already submitted")
        j.status, j.action, j.note, j.updated_at = "skipped", "skip", "Skipped by you", time.time()
    return Accepted()
