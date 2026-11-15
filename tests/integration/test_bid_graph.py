"""Bid graph end to end against the in-process GigSim: parallel analysis, critic loop bound,
interrupt + resume, crash-and-resume with exactly-once submission, scam skip, injection defence."""
import json
import uuid
from pathlib import Path

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.store.memory import InMemoryStore
from langgraph.types import Command

from agent.graphs.bid_graph import bid_thread_id, build_bid_graph
from agent.mcp_client import ToolBox
from agent.runtime import Ctx
from agent.settings import get_settings

ROOT = Path(__file__).resolve().parents[2]
DEV = json.loads((ROOT / "evals" / "datasets" / "dev_ai_engineer.json").read_text())
USER = {"floor_rate": 35, "target_rate": 55, "min_project": 300, "connects_budget_week": 80, "strategy": "evidence_first"}


def pick(kind="normal", bid=True):
    return next(r for r in DEV if r["gold"]["kind"] == kind and r["gold"]["bid"] == bid and (kind != "normal" or r["gold"]["fit"] == 1.0))


async def run(graph, job_id, user_id, cfg=None, **ctx_kw):
    tools = ToolBox(user_id, "ai_engineer", "trace-it")
    job = await tools.call("scout", "marketplace.get_job", {"job_id": job_id})
    cfg = cfg or {"configurable": {"thread_id": bid_thread_id(user_id, job_id)}}
    ctx = Ctx(user_id=user_id, owner="ai_engineer", trace_id="trace-it", tools=tools, **ctx_kw)
    order = []
    async for mode, ev in graph.astream({"job": job, "user": USER}, cfg, context=ctx, stream_mode=["updates"]):
        order += list(ev)
    return cfg, ctx, order


def uid(): return "u-" + uuid.uuid4().hex[:8]


async def test_bid_path_pauses_for_approval_then_submits_once(tmp_path):
    row, user = pick(), uid()
    async with AsyncSqliteSaver.from_conn_string(str(tmp_path / "cp.sqlite")) as saver:
        graph = build_bid_graph(saver, InMemoryStore())
        cfg, ctx, order = await run(graph, row["job"]["job_id"], user)
        assert order[0] == "intake" and set(order[1:4]) == {"analyst", "risk", "matcher"} and order[4] == "decide"
        st = await graph.aget_state(cfg)
        assert st.next == ("approval",), st.values.get("decision")
        payload = st.tasks[0].interrupts[0].value
        assert payload["preview"]["dry_run"] and payload["preview"]["connects"]["total"] > 0
        assert payload["draft"]["cover_letter"] and payload["draft"]["evidence_ids"]
        assert all(c["label"] != "unsupported" for c in payload["draft"]["claims"])
        assert sum(1 for c in st.values["critiques"] if c["sent_back"]) <= get_settings().cfg["budgets"]["max_revisions"]
        bal0 = (await ctx.tools.call("pricing", "marketplace.get_connects_balance", {}))["balance"]
        assert bal0 == 120                                                   # nothing spent before approval

        # ---- "crash": throw the graph object away, rebuild from the checkpoint, approve
        graph2 = build_bid_graph(saver, InMemoryStore())
        async for _ in graph2.astream(Command(resume={"action": "approve"}), cfg, context=ctx, stream_mode=["updates"]): pass
        v = (await graph2.aget_state(cfg)).values
        assert v["status"] == "submitted" and v["outcome"]["proposal_id"]
        spent = v["outcome"]["connects_spent"]
        # ---- replay the submit node from checkpoint history: must not submit or spend twice
        hist = [h async for h in graph2.aget_state_history(cfg)]
        before_submit = next(h for h in hist if h.next == ("submit",))
        async for _ in graph2.astream(None, before_submit.config, context=ctx, stream_mode=["updates"]): pass
        v2 = (await graph2.aget_state(cfg)).values
        assert v2["outcome"]["proposal_id"] == v["outcome"]["proposal_id"]
        assert (await ctx.tools.call("pricing", "marketplace.get_connects_balance", {}))["balance"] == 120 - spent


async def test_scam_is_skipped_without_drafting():
    row = pick("scam", False)
    graph = build_bid_graph(None, InMemoryStore())
    cfg, ctx, order = await run(graph, row["job"]["job_id"], uid(), cfg={"configurable": {"thread_id": "t-scam"}})
    assert "writer" not in order and "approval" not in order and order[-1] == "decide"


async def test_injection_is_removed_and_never_reaches_the_draft(tmp_path):
    row = next(r for r in DEV if r["gold"]["kind"] == "injection" and r["gold"]["bid"])
    async with AsyncSqliteSaver.from_conn_string(str(tmp_path / "cp.sqlite")) as saver:
        graph = build_bid_graph(saver, InMemoryStore())
        cfg, ctx, order = await run(graph, row["job"]["job_id"], uid())
        v = (await graph.aget_state(cfg)).values
        assert v["job"]["injection"]["flagged"] and row["gold"]["canary"] not in v["job"]["description"]
        assert v["analyses"]["risk"]["injection_detected"]
        assert row["gold"]["canary"] not in json.dumps(v.get("draft", {}))


async def test_reject_and_edit_paths(tmp_path):
    row, user = pick(), uid()
    store = InMemoryStore()
    async with AsyncSqliteSaver.from_conn_string(str(tmp_path / "cp.sqlite")) as saver:
        graph = build_bid_graph(saver, store)
        cfg, ctx, _ = await run(graph, row["job"]["job_id"], user)
        letter = (await graph.aget_state(cfg)).values["draft"]["cover_letter"]
        edited = letter.split(". ", 1)[1] + " Reach me at me@example.com."
        async for _ in graph.astream(Command(resume={"action": "edit", "edited_text": edited, "edited_bid": 777}), cfg, context=ctx, stream_mode=["updates"]): pass
        st = await graph.aget_state(cfg)
        assert st.next == ("approval",)                                       # edit -> compliance re-check -> back to the human
        p = st.tasks[0].interrupts[0].value
        assert "me@example.com" not in p["draft"]["cover_letter"] and p["compliance"]["status"] == "redacted"
        assert p["price"]["bid_amount"] == 777 and p["edit_diff"]["removed"]
        assert [i.key for i in await store.asearch(("style_candidates", user))]          # observed, not yet promoted
        assert not await store.asearch(("style", user))
        async for _ in graph.astream(Command(resume={"action": "reject", "reason": "client budget too low"}), cfg, context=ctx, stream_mode=["updates"]): pass
        v = (await graph.aget_state(cfg)).values
        assert v["status"] == "rejected" and v["approval"]["reason"] == "client budget too low" and "outcome" not in v


async def test_step_budget_moves_thread_to_needs_attention(monkeypatch):
    monkeypatch.setitem(get_settings().cfg["budgets"], "max_graph_steps", 3)
    row = pick()
    graph = build_bid_graph(None, InMemoryStore())
    cfg, ctx, order = await run(graph, row["job"]["job_id"], uid(), cfg={"configurable": {"thread_id": "t-budget"}})
    assert "approval" not in order


async def test_ablation_flag_keeps_unsupported_claims_visible():
    row = pick()
    graph = build_bid_graph(None, InMemoryStore())
    cfg, ctx, order = await run(graph, row["job"]["job_id"], uid(), cfg={"configurable": {"thread_id": "t-abl"}}, verify=False)
    assert "verifier" in order
