"""Conversation graph: a scam reply is recognised and answered with the fixed on-platform wording;
nothing is sent before approval; an approved reply is sent exactly once."""
import json
import uuid
from importlib import import_module
from pathlib import Path

import httpx
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore
from langgraph.types import Command

from agent.graphs.conversation_graph import build_conversation_graph, conversation_thread_id
from agent.mcp_client import ToolBox
from agent.runtime import Ctx
from gigsim.app import app

ROOT = Path(__file__).resolve().parents[2]
DEV = json.loads((ROOT / "evals" / "datasets" / "dev_ai_engineer.json").read_text())
LETTER = "For a SaaS client I built a retrieval assistant over 4,200 help-centre articles and it deflected 31% of tickets. " * 2


async def _submitted_thread(tools: ToolBox, kind: str, monkeypatch) -> str:
    module = import_module("gigsim.app")
    score = module.score_proposal

    def replying_client(*args, **kwargs):
        return {**score(*args, **kwargs), "replied": True}

    monkeypatch.setattr(module, "score_proposal", replying_client)
    job = next(r["job"] for r in DEV if r["gold"]["kind"] == kind)
    d = await tools.call("gateway", "marketplace.create_proposal_draft", {"job_id": job["job_id"], "cover_letter": LETTER, "bid_amount": 500, "idempotency_key": f"d-{uuid.uuid4().hex}"})
    r = await tools.call("gateway", "marketplace.submit_proposal", {"draft_id": d["draft_id"], "idempotency_key": f"s-{uuid.uuid4().hex}"})
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://gigsim") as c:
        await c.post("/admin/advance?seconds=7200", headers={"Authorization": "Bearer gigsim-dev-token", "X-Account": tools.ident.user})
    return r["thread_id"]


async def test_scam_reply_is_flagged_and_sent_only_after_approval(monkeypatch):
    user = "u-" + uuid.uuid4().hex[:8]
    tools = ToolBox(user, "ai_engineer", "trace-conv")
    thread = await _submitted_thread(tools, "scam", monkeypatch)
    graph = build_conversation_graph(InMemorySaver(), InMemoryStore())
    cfg = {"configurable": {"thread_id": conversation_thread_id(user, thread)}}
    ctx = Ctx(user_id=user, owner="ai_engineer", tools=tools)
    async for _ in graph.astream({"thread_id": thread, "user": {"floor_rate": 35}}, cfg, context=ctx, stream_mode=["updates"]): pass
    st = await graph.aget_state(cfg)
    assert st.next == ("approval",)
    p = st.tasks[0].interrupts[0].value
    assert p["kind"] == "message" and p["intent"]["intent"] == "scam_signal"
    assert "on the platform" in p["reply"]["text"] and p["preview"]["dry_run"]
    msgs = await tools.call("liaison", "marketplace.list_messages", {"thread_id": thread})
    assert all(m["from"] == "client" for m in msgs["messages"])                 # nothing sent yet
    async for _ in graph.astream(Command(resume={"action": "approve"}), cfg, context=ctx, stream_mode=["updates"]): pass
    v = (await graph.aget_state(cfg)).values
    assert v["status"] == "sent"
    msgs = await tools.call("liaison", "marketplace.list_messages", {"thread_id": thread})
    assert sum(m["from"] == "freelancer" for m in msgs["messages"]) == 1


async def test_edit_with_contact_details_is_cleaned_before_sending(monkeypatch):
    user = "u-" + uuid.uuid4().hex[:8]
    tools = ToolBox(user, "ai_engineer", "trace-conv")
    thread = await _submitted_thread(tools, "scam", monkeypatch)
    graph = build_conversation_graph(InMemorySaver(), InMemoryStore())
    cfg = {"configurable": {"thread_id": conversation_thread_id(user, thread)}}
    ctx = Ctx(user_id=user, owner="ai_engineer", tools=tools)
    async for _ in graph.astream({"thread_id": thread, "user": {"floor_rate": 35}}, cfg, context=ctx, stream_mode=["updates"]): pass
    async for _ in graph.astream(Command(resume={"action": "edit", "edited_text": "Sure, write to me at me@example.com and we can talk here."}), cfg, context=ctx, stream_mode=["updates"]): pass
    msgs = await tools.call("liaison", "marketplace.list_messages", {"thread_id": thread})
    sent = [m for m in msgs["messages"] if m["from"] == "freelancer"]
    assert len(sent) == 1 and "example.com" not in sent[0]["text"]
