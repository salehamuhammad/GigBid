"""Proposals (pipeline board), approvals (the human gate) and client conversations."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select

from apps.api.auth.security import CurrentUser
from apps.api.db import Approval, Conversation, Proposal, User, session
from apps.api.schemas import Accepted, ApprovalOut, ConversationOut, DecisionIn, ProposalCard
from worker.queue import enqueue

router = APIRouter(prefix="/api", tags=["workflow"])


def _ap(a: Approval) -> ApprovalOut:
    return ApprovalOut(id=a.id, kind=a.kind, ref=a.ref, status=a.status, payload=a.payload, decision=a.decision or {}, created_at=a.created_at)


@router.get("/proposals", response_model=list[ProposalCard])
def pipeline(user: User = CurrentUser):
    """Pipeline board: drafted, submitted, viewed, replied, interview, hired, lost (and rejected by you)."""
    with session() as s:
        return [ProposalCard(id=p.id, job_id=p.job_id, title=p.title, category=p.category, stage=p.stage, bid=p.bid, connects=p.connects, strategy=p.strategy,
                             conversation_id=p.conversation_id, reject_reason=p.reject_reason, updated_at=p.updated_at)
                for p in s.scalars(select(Proposal).where(Proposal.user_id == user.id).order_by(Proposal.updated_at.desc()))]


@router.get("/approvals", response_model=list[ApprovalOut])
def approvals(status: str = "pending", user: User = CurrentUser):
    with session() as s:
        return [_ap(a) for a in s.scalars(select(Approval).where(Approval.user_id == user.id, Approval.status.in_(status.split(","))).order_by(Approval.created_at.desc()).limit(100))]


@router.get("/approvals/{approval_id}", response_model=ApprovalOut)
def approval(approval_id: str, user: User = CurrentUser):
    with session() as s:
        a = s.get(Approval, approval_id)
        if not a or a.user_id != user.id: raise HTTPException(404, "Approval not found")
        return _ap(a)


@router.post("/approvals/{approval_id}/decision", response_model=Accepted)
async def decide(approval_id: str, body: DecisionIn, request: Request, user: User = CurrentUser):
    """Approve, edit, reject (with a reason) or regenerate one paragraph. This is the only way a
    proposal is submitted, a message is sent, or Connects are spent."""
    with session() as s:
        a = s.get(Approval, approval_id)
        if not a or a.user_id != user.id: raise HTTPException(404, "Approval not found")
        if a.status != "pending": raise HTTPException(409, f"This approval is already {a.status}")
        kind = a.kind
    if body.action == "reject" and not (body.reason or "").strip(): raise HTTPException(422, "Give a reason when rejecting")
    if body.action == "edit" and not (body.edited_text or "").strip(): raise HTTPException(422, "Edited text is empty")
    if body.action == "regenerate" and kind != "proposal": raise HTTPException(422, "Only proposals can be regenerated")
    task = "resume_bid" if kind == "proposal" else "resume_conversation"
    await enqueue(task, user.id, approval_id, body.model_dump(), request.state.trace_id, key=f"resume:{approval_id}")
    return Accepted(detail={"approve": "Approved - sending", "edit": "Edit saved - re-checking", "reject": "Rejected", "regenerate": "Regenerating"}[body.action])


@router.get("/conversations", response_model=list[ConversationOut])
def conversations(user: User = CurrentUser):
    with session() as s:
        out = []
        for c in s.scalars(select(Conversation).where(Conversation.user_id == user.id).order_by(Conversation.updated_at.desc())):
            a = s.scalars(select(Approval).where(Approval.user_id == user.id, Approval.kind == "message", Approval.ref == c.conversation_id, Approval.status == "pending")).first()
            out.append(ConversationOut(conversation_id=c.conversation_id, job_id=c.job_id, title=c.title, status=c.status, intent=c.intent, messages=c.messages or [], approval=_ap(a) if a else None, updated_at=c.updated_at))
        return out


@router.post("/conversations/{conversation_id}/draft", response_model=Accepted)
async def draft_reply(conversation_id: str, request: Request, user: User = CurrentUser):
    with session() as s:
        if not s.scalars(select(Conversation).where(Conversation.user_id == user.id, Conversation.conversation_id == conversation_id)).first(): raise HTTPException(404, "Conversation not found")
    await enqueue("run_conversation", user.id, conversation_id, request.state.trace_id, key=f"conv:{user.id}:{conversation_id}:manual")
    return Accepted(detail="Drafting a reply")
