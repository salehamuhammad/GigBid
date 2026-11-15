"""Matched retrieval and proposal comparison through GigBid's real approval gate."""
from __future__ import annotations

import argparse
import asyncio
import json
import time

import httpx

from agent.llm import extract_json, get_llm, load_prompt, render
from agent.settings import get_settings
from evals.runners.baselines import _verify
from evals.runners.common import (
    PERSONAS,
    RESULTS,
    bootstrap_ci,
    dev,
    env_info,
    job_text,
    mean,
    mount_gigsim,
    pctl,
    run_to_gate,
    sample,
    save,
    sign_test_p,
)
from evals.runners.judge import Score
from evals.runners.rag_eval import score
from rag.rerank import CrossEncoderReranker, get_reranker
from rag.retriever import get_retriever

ARMS = ("v0_naive", "best", "v9_skill_graph")
SEED = 4016


def metric(rows, key):
    values = [row[key] for row in rows if row.get(key) is not None]
    return mean(values) if values else None


def summarize(rows):
    drafts = [r for r in rows if r.get("proposal")]
    scored = [r for r in drafts if r.get("replied") is not None]
    positive = [r for r in rows if r["gold_count"]]
    negatives = [r for r in rows if not r["gold_count"]]
    times = [r["latency_s"] for r in rows if "latency_s" in r]
    draft_times = [r["latency_s"] for r in drafts]
    return {
        "jobs": len(rows), "drafts": len(drafts), "simulator_scored": len(scored),
        "judge_scored": sum(r.get("judge_overall") is not None for r in drafts),
        "graph_errors": sum("graph_error" in r for r in rows),
        "heuristic_fallbacks": sum(r.get("heuristic_fallbacks", 0) for r in rows),
        "recall@5": metric(positive, "recall@5"), "mrr": metric(positive, "mrr"),
        "ndcg@10": metric(positive, "ndcg@10"), "negative_refusal_rate": metric(negatives, "refused"),
        "unsupported_per_proposal": metric(drafts, "unsupported"),
        "judge_overall": metric(drafts, "judge_overall"),
        "reply_rate_per_scored_proposal": metric(scored, "replied"),
        "hire_rate_per_scored_proposal": metric(scored, "hired"),
        "replies_per_assigned_job": mean(r.get("replied") is True for r in rows) if rows else None,
        "p50_job_s": round(pctl(times, .50), 3) if times else None,
        "p95_job_s": round(pctl(times, .95), 3) if times else None,
        "p50_proposal_s": round(pctl(draft_times, .50), 3) if draft_times else None,
        "p95_proposal_s": round(pctl(draft_times, .95), 3) if draft_times else None,
        "cost_per_job_usd": average_cost(rows), "cost_per_proposal_usd": average_cost(drafts),
        "tokens_per_job": metric(rows, "tokens"), "tokens_per_proposal": metric(drafts, "tokens"),
    }


def average_cost(rows):
    costs = [r["cost_usd"] for r in rows if "cost_usd" in r]
    return round(sum(costs) / len(costs), 8) if costs else None


async def evaluate(client, persona, row, arm):
    job, gold = row["job"], row["gold"]
    jid = job["job_id"]
    result = {"persona": persona, "job_id": jid, "kind": gold["kind"],
              "category": gold["category"], "gold_count": len(gold["evidence"]), "arm": arm}
    # The same process-local setting is used by the isolated, in-memory Portfolio MCP server.
    get_settings().cfg["rag"]["deployed_variant"] = arm
    retriever = get_retriever(persona, arm)
    retrieved = retriever.retrieve(job_text(job), k=10)
    ids = [hit.doc_id for hit in retrieved.hits]
    result.update(retrieved=ids, refused=retrieved.refused or not ids)
    if gold["evidence"]:
        result.update(score(ids, gold["evidence"]))
    started = time.perf_counter()
    try:
        async with asyncio.timeout(360):
            state = await run_to_gate(jid, persona, user_id="retrieval-matched")
    except Exception as exc:
        result.update(graph_error=type(exc).__name__, latency_s=time.perf_counter() - started)
        return result
    usage = state.get("usage", [])
    result.update(decision=(state.get("decision") or {}).get("action"), latency_s=state["_latency_s"],
                  tokens=sum(u.get("input_tokens", 0) + u.get("output_tokens", 0) for u in usage),
                  cost_usd=sum(u.get("cost_usd", 0) for u in usage),
                  heuristic_fallbacks=sum(u.get("model") == "heuristic-fallback" for u in usage))
    if not state["_at_gate"]:
        return result
    draft = state["draft"]
    letter = draft["cover_letter"]
    result.update(proposal=letter, unsupported=_verify(persona, letter, draft["evidence_ids"])["unsupported"])
    response = await client.post("/eval/score", json={
        "job_id": jid, "cover_letter": letter, "bid_amount": state["price"]["bid_amount"],
        "screening_answers": [answer["answer"] for answer in draft.get("screening_answers", [])],
    })
    result["simulator_status"] = response.status_code
    if response.is_success:
        outcome = response.json()
        result.update({k: outcome[k] for k in ("p_reply", "replied", "hired")})
    prompt = load_prompt("judge")
    system = prompt["system"] + "\nReturn only JSON matching " + json.dumps(Score.model_json_schema())
    for _ in range(3):
        try:
            response, usage = await get_llm().complete("judge", system, render(
                prompt["user"], {"job_post": job_text(job), "proposal": letter}))
            rating = Score.model_validate(extract_json(response)).model_dump()
            result.update(judge=rating, judge_overall=rating["overall"], judge_usage=usage)
            result.pop("judge_error", None)
            break
        except Exception as exc:
            result["judge_error"] = type(exc).__name__
    return result


def paired(rows, candidate):
    by_job = {(row["job_id"], row["arm"]): row for row in rows}
    differences = []
    both_scored = []
    for r in rows:
        if r["arm"] != ARMS[0] or (r["job_id"], candidate) not in by_job:
            continue
        other = by_job[r["job_id"], candidate]
        diff = int(other.get("replied") is True) - int(r.get("replied") is True)
        differences.append(diff)
        if other.get("replied") is not None and r.get("replied") is not None:
            both_scored.append(diff)
    return {"assigned_pairs": len(differences), "both_proposals_scored": len(both_scored),
            "replies_per_job_delta": mean(differences), "paired_bootstrap_95ci": bootstrap_ci(differences),
            "paired_reply_p": sign_test_p(differences.count(1), differences.count(-1))}


async def run(per_persona, output, arms, max_new_rows):
    settings = get_settings()
    if settings.marketplace_mode != "gigsim" or settings.mcp_transport != "inprocess":
        raise SystemExit("Use MARKETPLACE_MODE=gigsim and MCP_TRANSPORT=inprocess for this benchmark.")
    if get_llm().offline:
        raise SystemExit("This comparison requires an open LLM profile.")
    if "best" in arms and not isinstance(get_reranker(), CrossEncoderReranker):
        raise SystemExit("The configured composition must use its actual cross-encoder.")
    if not settings.qdrant_url:
        raise SystemExit("Use the same BGE Qdrant indexes as the retrieval benchmark.")
    app = mount_gigsim()
    jobs = []
    for persona in PERSONAS:
        rows = [r for r in dev(persona) if r["gold"]["kind"] != "duplicate"]
        positive = [r for r in rows if r["gold"]["bid"] and r["gold"]["kind"] == "normal"]
        negative = [r for r in rows if not r["gold"]["bid"] and not r["gold"]["evidence"]]
        jobs.extend((persona, r) for r in sample(positive, per_persona - 1, SEED) + sample(negative, 1, SEED))
    plan = [(p, r, arm) for i, (p, r) in enumerate(jobs) for arm in arms[i % len(arms):] + arms[:i % len(arms)]]
    env = env_info()
    signature = {k: env[k] for k in ("dataset_sha256", "embeddings", "model_profile", "reranker", "vector_store")}
    signature.update(plan=[[p, r["job"]["job_id"], arm] for p, r, arm in plan], seed=SEED,
                     judge=get_llm().model_for("judge"))
    checkpoint = RESULTS / f"{output}.json"
    rows = []
    if checkpoint.exists():
        previous = json.loads(checkpoint.read_text(encoding="utf-8"))
        if previous["protocol"] != signature:
            raise ValueError("Existing checkpoint belongs to a different benchmark.")
        rows = previous["rows"]
        if previous["complete"]:
            return
    deployed = get_settings().cfg["rag"]["deployed_variant"]
    headers = {"Authorization": f"Bearer {get_settings().gigsim_token}", "X-Account": "retrieval-matched"}
    stop = len(rows) + max_new_rows if max_new_rows is not None else len(plan)
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://gigsim", headers=headers) as client:
            for persona, row, arm in plan[len(rows):stop]:
                item = await evaluate(client, persona, row, arm)
                rows.append(item)
                print(len(rows), len(plan), persona, item["job_id"], arm, item.get("decision"), flush=True)
                subsets = {a: [row for row in rows if row["arm"] == a] for a in arms}
                save(output, {"env": env, "protocol": signature, "complete": len(rows) == len(plan),
                              "summary": {a: summarize(items) for a, items in subsets.items()},
                              "by_persona": {a: {p: summarize([r for r in items if r["persona"] == p])
                                                 for p in PERSONAS} for a, items in subsets.items()},
                              "by_job_type": {a: {kind: summarize([r for r in items if r["kind"] == kind])
                                                   for kind in sorted({r["kind"] for r in items})}
                                              for a, items in subsets.items()},
                              "paired_vs_v0": {a: paired(rows, a) for a in arms if a != ARMS[0] and ARMS[0] in arms},
                              "rows": rows})
    finally:
        get_settings().cfg["rag"]["deployed_variant"] = deployed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--per-persona", type=int, default=5)
    parser.add_argument("--output", default="retrieval_outcomes_open")
    parser.add_argument("--arms", choices=ARMS, nargs="+", default=ARMS)
    parser.add_argument("--max-new-rows", type=int)
    args = parser.parse_args()
    if args.per_persona < 2:
        parser.error("--per-persona must include at least one positive and one negative job")
    if args.max_new_rows is not None and args.max_new_rows < 1:
        parser.error("--max-new-rows must be positive")
    asyncio.run(run(args.per_persona, args.output, tuple(dict.fromkeys(args.arms)), args.max_new_rows))


if __name__ == "__main__":
    main()
