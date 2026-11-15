"""Client Liaison: read client replies, classify intent, draft a response, offer interview slots
(MCP: marketplace read, write after approval; workspace; portfolio read)."""
from __future__ import annotations

import re
import time

from langgraph.config import get_config
from langgraph.types import interrupt
from pydantic import BaseModel

from agent.guardrails import rules, scan_untrusted, wrap_untrusted
from agent.handoffs import ApprovalDecision, IntentReport, ReplyDraft
from agent.mcp_client import ToolError
from agent.nodes.compliance import check
from agent.runtime import Node, node


class ReplyText(BaseModel):
    text: str


def heuristic_intent(text: str, injection: bool) -> IntentReport:
    signals = [code for code, sig in rules()["risk_signals"].items() if any(re.search(p, text) for p in sig["patterns"])]
    if re.search(r"(?i)\b(your|send me|share).{0,30}\b(email|phone|number|address|whatsapp)\b", text): signals.append("asks_personal_contact")
    if signals: return IntentReport(intent="scam_signal", confidence=0.9, signals=signals, injection_detected=injection)
    if re.search(r"(?i)\b(call|interview|meet(ing)?|zoom|video chat|schedule|available)\b", text): return IntentReport(intent="interview_request", confidence=0.8, injection_detected=injection)
    if re.search(r"(?i)\b(budget|price|rate|discount|cheaper|flexib|lower|\$\s?\d+|too (high|expensive))\b", text): return IntentReport(intent="negotiation", confidence=0.75, injection_detected=injection)
    if "?" in text: return IntentReport(intent="question", confidence=0.7, injection_detected=injection)
    return IntentReport(intent="other", confidence=0.5, injection_detected=injection)


@node("load")
async def load(n: Node) -> dict:
    th = await n.tool("liaison", "marketplace.list_messages", {"thread_id": n.state["thread_id"]})
    msgs = th.get("messages", [])
    last = next((m for m in reversed(msgs) if m.get("from") == "client"), None)
    if last is None or (msgs and msgs[-1].get("from") != "client"):
        return {"messages": msgs, "status": "idle", "_summary": "no unanswered client message"}
    scan = scan_untrusted(last["text"], defend=n.ctx.defences)
    return {"messages": msgs, "last_client_message": {**last, "text_raw": last["text"], "text": scan["cleaned"] if n.ctx.defences else last["text"], "injection": scan["flagged"]},
            "status": "reading", "job": {**(n.state.get("job") or {}), "job_id": th.get("job_id"), "client_id": th.get("client_id")},
            "_summary": f"{len(msgs)} messages" + ("; embedded instruction removed" if scan["flagged"] else "")}


def _history(msgs: list[dict]) -> list[dict]:
    return [{"from": m["from"], "text": scan_untrusted(m["text"])["cleaned"][:400]} for m in msgs[-6:-1]]


@node("classify")
async def classify(n: Node) -> dict:
    m = n.state["last_client_message"]
    base = heuristic_intent(m["text_raw"], m["injection"])
    rep = await n.llm("intent", "intent", {"history": _history(n.state["messages"]), "message": wrap_untrusted(m["text"], "client_message")}, IntentReport, lambda: base)
    if base.intent == "scam_signal":      # rule-detected scam signals are never downgraded by a model
        rep = rep.model_copy(update={"intent": "scam_signal", "signals": sorted(set(base.signals + rep.signals))})
    rep = rep.model_copy(update={"injection_detected": base.injection_detected or rep.injection_detected})
    return {"intent": rep.model_dump(), "_summary": f"{rep.intent} ({rep.confidence:.2f})" + ("; injection flagged" if rep.injection_detected else "")}


@node("slots")
async def slots(n: Node) -> dict:
    res = await n.tool("liaison", "workspace.find_free_slots", {"days": 5, "duration_minutes": 30, "limit": 3})
    return {"slots": res.get("slots", []), "_summary": f"{len(res.get('slots', []))} free slots"}


@node("draft")
async def draft(n: Node) -> dict:
    st = n.state; m, intent, user = st["last_client_message"], st["intent"]["intent"], st.get("user", {})
    floor, bid = user.get("floor_rate", 0), (st.get("job") or {}).get("bid_amount")
    sl = st.get("slots") or []
    evidence = []
    if intent == "question":
        r = await n.tool("liaison", "portfolio.search_evidence", {"requirement": m["text"][:500], "k": 2})
        evidence = [] if r.get("refused") else r.get("evidence", [])

    def fallback() -> ReplyText:
        if intent == "scam_signal":
            return ReplyText(text="Thanks for the reply. I keep all communication and payment on the platform, which protects both of us, so I will not move this conversation or payment elsewhere. "
                                  "If you would like to continue here, I am glad to answer any question about the project.")
        if intent == "interview_request":
            times = "; ".join(s["label"] for s in sl) or "a time that suits you this week"
            return ReplyText(text=f"Happy to talk it through. I am free at these times: {times}. Tell me which works and I will hold it. A call through the platform is fine for me.")
        if intent == "negotiation":
            return ReplyText(text="Thanks for being direct about budget. " + (f"My bid of ${bid:.0f} reflects the full scope as posted. " if bid else "") +
                                  "Rather than cut the rate, I would suggest trimming scope: we agree a smaller first milestone at a price that fits, and extend if you are happy with it. Which deliverable matters most to you?")
        if evidence:
            e = evidence[0]
            return ReplyText(text=f"Good question. The closest example in my portfolio is {e['title']}: {e['snippet'][:220].strip()} I am happy to go deeper on any part of it. For your project, the first milestone would be a small working slice so you can judge the approach early.")
        return ReplyText(text="Thanks for the message. Could you tell me a little more about what you would like to see first, so I answer the right question?")

    r = await n.llm("liaison", "liaison", {"intent": intent, "floor": floor, "bid": bid, "slots": [s["label"] for s in sl], "evidence": [{"id": e["id"], "title": e["title"], "snippet": e["snippet"]} for e in evidence],
                                           "history": _history(st["messages"]), "message": wrap_untrusted(m["text"], "client_message")}, ReplyText, fallback)
    text = fallback().text if intent == "scam_signal" else r.text          # the scam reply is fixed wording, never model-written
    v = await check(n, text, 4000)
    reply = ReplyDraft(thread_id=st["thread_id"], text=v.cleaned_text, intent=intent, slots=sl, evidence_ids=[e["id"] for e in evidence])
    return {"reply": reply.model_dump(), "compliance": v.model_dump(), "status": "blocked" if v.status == "blocked" else "drafted", "_summary": f"reply drafted ({len(v.cleaned_text.split())} words), compliance {v.status}"}


@node("approval", counts=False)
async def approve_reply(n: Node) -> dict:
    st = n.state; reply = st["reply"]; tid = get_config()["configurable"]["thread_id"]
    key = f"msg:{tid}:{st['last_client_message']['id']}"
    preview = await n.tool("liaison", "marketplace.send_message", {"thread_id": st["thread_id"], "text": reply["text"], "idempotency_key": key, "dry_run": True})
    decision = ApprovalDecision.model_validate(interrupt({"kind": "message", "thread_id": tid, "conversation_id": st["thread_id"], "job_id": (st.get("job") or {}).get("job_id"), "reply": reply,
                                                          "intent": st["intent"], "client_message": st["last_client_message"]["text"], "compliance": st.get("compliance"), "preview": preview}))
    d = decision.model_dump()
    if decision.action == "edit" and decision.edited_text:
        v = await check(n, decision.edited_text, 4000)          # edits are re-checked by Compliance before anything is sent
        if v.status == "blocked":
            return {"approval": d, "compliance": v.model_dump(), "status": "blocked", "_summary": "edit blocked by compliance"}
        return {"approval": {**d, "action": "approve"}, "reply": {**reply, "text": v.cleaned_text}, "compliance": v.model_dump(), "status": "approved", "_summary": "edited and approved"}
    return {"approval": d, "status": {"approve": "approved", "reject": "rejected"}.get(decision.action, "rejected"), "_summary": decision.action}


@node("send", counts=False)
async def send(n: Node) -> dict:
    st = n.state; reply = st["reply"]; tid = get_config()["configurable"]["thread_id"]
    if (st.get("approval") or {}).get("action") != "approve":
        return {"status": "needs_attention", "errors": ["send reached without an approval"]}
    key = f"msg:{tid}:{st['last_client_message']['id']}"
    try:
        r = await n.tool("liaison", "marketplace.send_message", {"thread_id": st["thread_id"], "text": reply["text"], "idempotency_key": key})
    except ToolError as e:
        return {"status": "blocked", "errors": [str(e)[:200]]}
    if r.get("status") == "draft_awaiting_confirmation_on_upwork":
        return {"outcome": r, "status": "awaiting_upwork", "_summary": "Upwork message draft awaiting confirmation"}
    out = {**r, "sent_at": time.time()}
    if st["intent"]["intent"] == "interview_request" and st.get("slots"):
        s0 = st["slots"][0]
        out["hold"] = await n.tool("liaison", "workspace.create_interview_hold", {"start": s0["start"], "title": f"Client call ({st['thread_id']})", "idempotency_key": f"hold:{key}"})
        out["email_draft"] = await n.tool("liaison", "workspace.create_email_draft", {"subject": f"Prep notes: client call {s0['label']}", "body": f"Thread {st['thread_id']}. Client asked: {st['last_client_message']['text'][:300]}",
                                                                                         "idempotency_key": f"mail:{key}"})
    return {"outcome": out, "status": "sent", "_summary": f"message {r.get('status')}" + ("; tentative hold placed" if out.get("hold") else "")}
