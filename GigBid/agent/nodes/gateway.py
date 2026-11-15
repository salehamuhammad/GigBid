"""The approval gate (R4, C5) and the only nodes that can reach marketplace write tools.

  approval    interrupt() with the full approval payload; resumes with the human's decision
  apply_edit  diff the user's edit, feed style memory through the promotion rule, re-verify
  submit      create the draft and submit it, each with an idempotency key derived from the
              thread id -- so a crash, a retry or a double click can never submit or spend twice
"""
from __future__ import annotations

import hashlib
import time

from langgraph.config import get_config
from langgraph.types import interrupt

from agent.handoffs import ApprovalDecision, Claim
from agent.mcp_client import ToolError
from agent.memory import promotion_rules as rules
from agent.memory.store import Memory
from agent.runtime import Node, node
from rag import verify as V


def thread_id() -> str:
    return get_config()["configurable"]["thread_id"]


def _digest(draft: dict, price: dict) -> str:
    """Same text + same bid -> same key (a retry replays); an edited draft gets a new draft, never an old one."""
    return hashlib.sha1(f"{draft['cover_letter']}|{price['bid_amount']}".encode()).hexdigest()[:12]


def _answers(draft: dict) -> list[str]:
    return [a["answer"] for a in draft.get("screening_answers", [])]


@node("approval", counts=False)
async def approval(n: Node) -> dict:
    st = n.state; draft, price, job = st["draft"], st["price"], st["job"]
    tid = thread_id()
    preview = await n.tool("gateway", "marketplace.create_proposal_draft", {"job_id": job["job_id"], "cover_letter": draft["cover_letter"], "bid_amount": price["bid_amount"],
                                                                           "screening_answers": _answers(draft), "idempotency_key": f"preview:{tid}", "dry_run": True})
    ev = {k: {"id": k, "title": v.get("title"), "type": v.get("type"), "date": v.get("date"), "outcome": v.get("outcome"), "skills": v.get("skills", []), "text": v.get("text", "")[:900]}
          for k, v in (st.get("evidence") or {}).items() if k in draft.get("evidence_ids", [])}
    payload = {"kind": "proposal", "thread_id": tid, "job_id": job["job_id"], "title": job.get("title"), "draft": draft, "evidence": ev, "risk": st["analyses"]["risk"],
               "price": price, "critique": (st.get("critiques") or [None])[-1], "compliance": st.get("compliance"), "verification": st.get("verification"),
               "preview": preview, "edit_diff": (st.get("approval") or {}).get("diff"), "warnings": (st.get("approval") or {}).get("warnings", [])}
    decision = ApprovalDecision.model_validate(interrupt(payload))       # <- the graph stops here until a human answers in the UI
    d = decision.model_dump()
    status = {"approve": "approved", "edit": "editing", "reject": "rejected", "regenerate": "drafting"}[decision.action]
    return {"approval": d, "approvals": [{**d, "at": time.time()}], "preview": preview, "status": status, "_summary": decision.action + (f": {decision.reason}" if decision.reason else "")}


@node("apply_edit")
async def apply_edit(n: Node) -> dict:
    st = n.state; draft, ap = dict(st["draft"]), dict(st["approval"])
    before, after = draft["cover_letter"], (ap.get("edited_text") or draft["cover_letter"]).strip()
    diff = rules.diff_edit(before, after)
    learned = await Memory(n.store, n.ctx.user_id).record_edit(before, after, draft_id=f"{draft['job_id']}:{len(st.get('approvals') or [])}") if n.store is not None else {"patterns": [], "promoted": []}
    ev = [{"id": k, "text": v.get("text", "") + "\n" + v.get("title", "") + "\n" + v.get("code", ""), "skills": v.get("skills", [])} for k, v in (st.get("evidence") or {}).items()]
    cites = {c["text"]: c.get("evidence_ids", []) for c in draft.get("claims", [])}
    checks = V.verify_text(after, ev, cites)
    # The user's own words are not deleted, but a new claim with no evidence is shown as a warning before they approve.
    warnings = [f"Unverified claim you added: \"{c['text'][:120]}\" ({c['reason']})" for c in checks if c["label"] == "unsupported"]
    draft["cover_letter"] = after
    draft["claims"] = [Claim(text=c["text"], evidence_ids=c["evidence_ids"], label=c["label"], reason=c["reason"]).model_dump() for c in checks]
    if ap.get("edited_answers"):
        for a, new in zip(draft.get("screening_answers", []), ap["edited_answers"]): a["answer"] = new
    price = dict(st["price"])
    if ap.get("edited_bid"): price["bid_amount"] = ap["edited_bid"]; price["rationale"] = price.get("rationale", []) + [f"Bid set to ${ap['edited_bid']:.0f} by you"]
    ap |= {"diff": diff, "warnings": warnings, "learned": learned}
    return {"draft": draft, "price": price, "approval": ap, "verification": {**(st.get("verification") or {}), "unsupported_after": 0},
            "_summary": f"edit: -{len(diff['removed'])} +{len(diff['added'])} spans; {len(learned['patterns'])} style pattern(s) observed, {len(learned['promoted'])} promoted"}


@node("submit", counts=False)
async def submit(n: Node) -> dict:
    st = n.state; draft, price, job, tid = st["draft"], st["price"], st["job"], thread_id()
    if (st.get("approval") or {}).get("action") != "approve":            # defence in depth: no approval, no write
        return {"status": "needs_attention", "errors": ["submit reached without an approval"]}
    try:
        d = await n.tool("gateway", "marketplace.create_proposal_draft", {"job_id": job["job_id"], "cover_letter": draft["cover_letter"], "bid_amount": price["bid_amount"],
                                                                         "screening_answers": _answers(draft), "idempotency_key": f"draft:{tid}:{_digest(draft, price)}"})
        r = await n.tool("gateway", "marketplace.submit_proposal", {"draft_id": d["draft_id"], "idempotency_key": f"submit:{tid}"})
    except ToolError as e:
        return {"status": "blocked", "compliance": {**(st.get("compliance") or {}), "status": "blocked", "reason": f"Marketplace refused the proposal: {str(e)[:200]}"}, "errors": [str(e)[:200]]}
    if r.get("status") == "awaiting_confirmation_on_upwork":
        n.emit(event="info", message="Draft created on Upwork and awaiting your confirmation")
        return {"outcome": r, "status": "awaiting_upwork", "_summary": "Upwork draft awaiting confirmation"}
    n.emit(event="info", message=f"Submitted as {r.get('proposal_id')} ({r.get('status')}), {r.get('connects_spent', 0)} Connects spent")
    return {"outcome": {**r, "submitted_at": time.time()}, "status": "submitted", "_summary": f"{r.get('status')}: {r.get('proposal_id')}, {r.get('connects_spent', 0)} Connects"}
