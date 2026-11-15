"""`make demo`: one grounded proposal for one GigSim job, end to end, in one process.

Scouts a job the persona should bid on, runs the bid graph to the approval gate, prints the
draft with the evidence behind every claim and the dry-run preview, then stops. Nothing is sent.
    python -m scripts.demo [--persona ai_engineer] [--job-id dev-ai-00123] [--approve]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os

os.environ.setdefault("MCP_TRANSPORT", "inprocess")
os.environ.setdefault("GIGSIM_ERROR_RATE", "0")


async def main() -> None:
    ap = argparse.ArgumentParser(); ap.add_argument("--persona", default="ai_engineer"); ap.add_argument("--job-id"); ap.add_argument("--approve", action="store_true")
    a = ap.parse_args()
    import httpx
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.store.memory import InMemoryStore
    from langgraph.types import Command

    from agent.graphs.bid_graph import build_bid_graph
    from agent.mcp_client import ToolBox
    from agent.runtime import Ctx
    from agent.settings import get_settings
    from gigsim.app import app
    from mcp_servers.marketplace.adapters import gigsim
    gigsim.set_transport(httpx.ASGITransport(app=app))
    s = get_settings()
    prof = json.loads((s.data_dir / "personas" / a.persona / "profile.json").read_text())
    dev = json.loads((s.root / "evals" / "datasets" / f"dev_{a.persona}.json").read_text())
    job_id = a.job_id or next(r["job"]["job_id"] for r in dev if r["gold"]["bid"] and r["gold"]["kind"] == "normal" and r["gold"]["fit"] >= 0.8)
    tools = ToolBox("demo-user", a.persona, "trace-demo")
    job = await tools.call("scout", "marketplace.get_job", {"job_id": job_id})
    graph, cfg = build_bid_graph(InMemorySaver(), InMemoryStore()), {"configurable": {"thread_id": f"demo:{job_id}"}}
    ctx = Ctx(user_id="demo-user", owner=a.persona, trace_id="trace-demo", tools=tools)
    print(f"model profile: {s.profile_name}   marketplace: {s.marketplace_mode}\nJOB {job_id}: {job['title']}\n")
    async for mode, ev in graph.astream({"job": job, "user": prof}, cfg, context=ctx, stream_mode=["custom"]):
        if ev.get("event") == "node_end": print(f"  [{ev['node']:10s}] {ev.get('ms', 0):5d} ms  {ev.get('summary') or ''}")
    st = await graph.aget_state(cfg)
    if not st.next:
        print("\nDecision:", json.dumps(st.values.get("decision"), indent=2)); return
    p = st.tasks[0].interrupts[0].value
    print("\n--- DRAFT (waiting for approval) ---\n" + p["draft"]["cover_letter"])
    print("\n--- CLAIMS AND EVIDENCE ---")
    for c in p["draft"]["claims"]:
        if c["label"] != "not_a_claim": print(f"  [{c['label']:16s}] {c['text'][:90]}  <- {', '.join(c['evidence_ids']) or '-'}")
    pr = p["price"]
    print(f"\nBid ${pr['bid_amount']:.0f} ({pr['bid_type']})  Connects {pr['connects_cost']}  balance after: {p['preview']['balance_after']}")
    for r in pr["rationale"]: print("  -", r)
    if a.approve:
        async for _ in graph.astream(Command(resume={"action": "approve"}), cfg, context=ctx, stream_mode=["updates"]): pass
        print("\nSubmitted:", (await graph.aget_state(cfg)).values["outcome"])
    else:
        print("\nNothing was sent. Re-run with --approve to submit to GigSim.")


if __name__ == "__main__":
    asyncio.run(main())
