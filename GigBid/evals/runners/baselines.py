"""R&D question C: is the multi-agent design worth it? Same 50 dev jobs, three systems:
  (a) react       -- one ReAct agent holding all read tools (prompt: agent/prompts/single_agent.md)
  (b) supervisor  -- langgraph-supervisor over three ReAct workers (analyst, matcher, writer)
  (c) graph       -- GigBid's hand-built bid graph
Reports bid-or-skip accuracy, unsupported claims (same verifier for all), compliance violations
caught, GigSim P(reply) on drafted proposals, tokens and latency. REQUIRES a real model profile:
    MODEL_PROFILE=open GROQ_API_KEY=... python -m evals.runners.baselines --n 50
"""
from __future__ import annotations

import argparse
import asyncio
import time

import httpx

from agent.llm import extract_json, get_llm, load_prompt, render
from agent.nodes.compliance import run_rules
from agent.settings import get_settings
from evals.runners.common import (
    PERSONAS,
    RESULTS,
    dev,
    env_info,
    mean,
    mount_gigsim,
    pctl,
    profile,
    run_to_gate,
    sample,
    save,
)
from rag import verify as V


def _verify(persona, letter, ids):
    from rag.retriever import owner_index
    ix = owner_index(persona)
    ev = [{"id": i, "text": ix.docs[i].text, "skills": ix.docs[i].meta.get("skills") or []} for i in ids if i in ix.docs] or \
         [{"id": d.id, "text": d.text, "skills": d.meta.get("skills") or []} for d in ix.docs.values() if d.type == "case_study"]
    return V.summarize(V.verify_text(letter, ev))


async def react(row, persona, sup=False):
    from langgraph.prebuilt import create_react_agent

    from agent.mcp_client import ToolBox
    llm, p = get_llm(), profile(persona)
    tb = ToolBox("rq-c", persona)
    tools = [t for t in await tb.langchain_tools("single_agent") if t.name in ("get_job", "get_client_history", "search_evidence", "get_case_study", "get_market_stats")]
    pr = load_prompt("single_agent")
    sys_, user = pr["system"], render(pr["user"], {**p, "job_id": row["job"]["job_id"]})
    t0 = time.perf_counter()
    if sup:
        from langgraph_supervisor import create_supervisor
        by = {t.name: t for t in tools}
        def worker(name, tool_names, instructions):
            allowed = [by[tool_name] for tool_name in tool_names]
            model = llm.chat_model(name).bind_tools(allowed, parallel_tool_calls=False)
            return create_react_agent(model, allowed, name=name, prompt=instructions)

        workers = [
            worker("analyst", ("get_job", "get_client_history"), "Read the job and client history. Report requirements and scam signals. Call one tool at a time."),
            worker("matcher", ("search_evidence", "get_case_study"), "Find portfolio evidence for each requirement. Call one tool at a time."),
            worker("writer", ("get_market_stats",), sys_),
        ]
        agent = create_supervisor(
            workers, model=llm.chat_model("critic"), parallel_tool_calls=False,
            output_mode="full_history", add_handoff_back_messages=False,
            prompt="Use one handoff at a time. Coordinate the analyst, matcher and writer to decide bid or skip. "
                   "Give the writer the portfolio evidence and ask it for the final JSON. After receiving it, return the JSON.",
        ).compile()
    else:
        agent = create_react_agent(llm.chat_model("writer"), tools, prompt=sys_)
    out = await agent.ainvoke({"messages": [("user", user)]}, {"recursion_limit": 30})
    msgs = out["messages"]
    usage = []
    for message in msgs:
        if counts := getattr(message, "usage_metadata", None):
            model = message.response_metadata.get("model_name")
            cost = llm.cost(model, counts["input_tokens"], counts["output_tokens"]) if model else None
            usage.append({"model": model, "estimated_cost_usd": cost, **counts})
    toks = sum(call["total_tokens"] for call in usage)
    res = {}
    for message in reversed(msgs if sup else msgs[-1:]):
        if message.type != "ai" or (sup and message.name not in ("writer", "supervisor")):
            continue
        try:
            candidate = extract_json(str(message.content))
        except ValueError:
            continue
        if isinstance(candidate, dict) and candidate.get("decision") in ("bid", "skip"):
            res = candidate
            break
    action = res.get("decision")
    return {"action": action if action in ("bid", "skip") else "error", "letter": res.get("cover_letter") or "", "bid": res.get("bid_amount"), "ids": res.get("evidence_ids") or [], "tokens": toks, "latency": time.perf_counter() - t0, "usage": usage,
            "estimated_cost_usd": sum(call["estimated_cost_usd"] for call in usage) if usage and all(call["estimated_cost_usd"] is not None for call in usage) else None}


async def graph(row, persona):
    v = await run_to_gate(row["job"]["job_id"], persona)
    d = v.get("draft") or {}
    decision = (v.get("decision") or {}).get("action")
    action = "skip" if decision == "watch" else decision
    return {"action": action or "error", "graph_decision": decision, "letter": d.get("cover_letter", "") if v["_at_gate"] else "", "bid": (v.get("price") or {}).get("bid_amount"),
            "ids": d.get("evidence_ids", []), "tokens": sum(u.get("input_tokens", 0) + u.get("output_tokens", 0) for u in v.get("usage", [])), "latency": v["_latency_s"],
            "caught": len((v.get("compliance") or {}).get("violations", [])), "usage": v.get("usage", []),
            "estimated_cost_usd": sum(u.get("cost_usd", 0) for u in v.get("usage", []))}


SYSTEMS = ("react", "supervisor", "graph")


async def run(n, systems=SYSTEMS, output=None, concurrency=1):
    import json

    app = mount_gigsim()
    if get_llm().offline: raise SystemExit("Needs a real model: set MODEL_PROFILE=open and GROQ_API_KEY.")
    jobs = []
    per_persona, remainder = divmod(n, len(PERSONAS))
    for i, persona in enumerate(PERSONAS):
        count = per_persona + (i < remainder)
        if count:
            eligible = [row for row in dev(persona) if row["gold"]["kind"] != "duplicate"]
            jobs.extend((persona, row) for row in sample(eligible, count))
    out = {}
    plan = [[persona, row["job"]["job_id"]] for persona, row in jobs]
    checkpoint = RESULTS / f"{output}.json"
    if output and checkpoint.exists():
        previous = json.loads(checkpoint.read_text(encoding="utf-8"))
        if (previous.get("plan") != plan or previous.get("planned_systems") != list(systems)
                or previous["env"]["model_profile"] != get_settings().profile_name
                or previous["env"]["reranker"] != env_info()["reranker"]):
            raise ValueError("Existing checkpoint belongs to a different benchmark; choose a new --output")
        out = {system: previous[system] for system in systems if system in previous}
    headers = {"Authorization": f"Bearer {get_settings().gigsim_token}", "X-Account": "rq-c-scores"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://g", headers=headers) as c:
        for system in systems:
            rows = out.get(system, {}).get("rows", [])
            async def evaluate(p, r):
                started = time.perf_counter()
                try:
                    async with asyncio.timeout(180):
                        x = await (graph(r, p) if system == "graph" else react(r, p, sup=system == "supervisor"))
                except Exception as e: x = {"action": "error", "letter": "", "bid": None, "ids": [], "tokens": None, "latency": time.perf_counter() - started, "error": type(e).__name__, "http_status": getattr(e, "status_code", None)}
                x["correct"] = x["action"] == ("bid" if r["gold"]["bid"] else "skip")
                if x["letter"]:
                    x["claims"] = _verify(p, x["letter"], x["ids"]); x["violations"] = len(run_rules(x["letter"]).violations)
                    response = await c.post("/eval/score", json={"job_id": r["job"]["job_id"], "cover_letter": x["letter"], "bid_amount": x["bid"] or 100, "screening_answers": []})
                    outcome = response.json() if response.is_success else {}
                    x["p_reply"] = outcome.get("p_reply")
                    x["replied"] = outcome.get("replied")
                    x["simulator_http_status"] = response.status_code
                return {"persona": p, "job_id": r["job"]["job_id"], "kind": r["gold"]["kind"], **x}

            for start in range(len(rows), len(jobs), concurrency):
                rows.extend(await asyncio.gather(*(evaluate(p, r) for p, r in jobs[start:start + concurrency])))
                if output:
                    save(output, {"plan": plan, "planned_jobs_per_system": n, "planned_systems": systems,
                                  "complete": False, **out, system: {"n": len(rows), "rows": rows}})
            d = [x for x in rows if x["letter"]]
            scored = [x for x in d if x["replied"] is not None]
            costs = [x["estimated_cost_usd"] for x in rows if x.get("estimated_cost_usd") is not None]
            out[system] = {"n": len(rows), "errors": sum(x["action"] == "error" for x in rows), "bid_skip_accuracy": mean(x["correct"] for x in rows), "scam_accuracy": mean(x["correct"] for x in rows if x["kind"] == "scam"),
                           "unsupported_per_proposal": mean(x["claims"]["unsupported"] for x in d), "violations_in_output": sum(x["violations"] for x in d),
                           "mean_p_reply": mean(x["p_reply"] for x in d if x["p_reply"] is not None),
                           "simulator_reply_rate": mean(x["replied"] for x in scored) if scored else None,
                           "simulator_scored_n": len(scored),
                           "mean_estimated_cost_usd": mean(costs) if costs else None, "cost_samples": len(costs),
                           "tokens_per_job": mean(x["tokens"] for x in rows if x["tokens"] is not None), "latency_p95_s": round(pctl([x["latency"] for x in rows if x["latency"] is not None], .95), 2), "rows": rows}
            print(system, {k: v for k, v in out[system].items() if k != "rows"})
            if output:
                save(output, {"plan": plan, "planned_jobs_per_system": n, "planned_systems": systems,
                              "complete": len(out) == len(systems), **out})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=50)
    ap.add_argument("--output", default="baselines")
    ap.add_argument("--systems", nargs="+", choices=SYSTEMS, default=SYSTEMS)
    ap.add_argument("--concurrency", type=int, default=1)
    a = ap.parse_args()
    if a.n < 1 or a.concurrency < 1:
        ap.error("--n and --concurrency must be positive")
    asyncio.run(run(a.n, tuple(dict.fromkeys(a.systems)), a.output, a.concurrency))


if __name__ == "__main__":
    main()
