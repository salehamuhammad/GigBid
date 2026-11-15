"""Ablations: remove one component at a time and measure what it was worth.

RAG: start from the shipped `best` composition and switch off one component (rerank, hybrid,
decomposition, multi-vector index, outcome boost, corrective loop) -> Recall@5 / MRR / nDCG.
Graph: claim verification on vs off -> unsupported claims that reach the human.

    python -m evals.runners.ablation [--limit 100] [--graph-jobs 15]
"""
from __future__ import annotations

import argparse
import asyncio
from dataclasses import replace

import httpx

from agent.settings import get_settings
from evals.runners.common import PERSONAS, dev, mean, mount_gigsim, run_to_gate, sample, save
from evals.runners.rag_eval import evaluate
from rag import verify as claim_verifier
from rag.retriever import variants


def retrieval_ablations():
    best = variants()["best"]
    configs = {"best (shipped)": best}
    if best.rerank: configs["- rerank"] = replace(best, name="abl_no_rerank", rerank=False)
    if best.retrieval == "graph": configs["- skill graph (hybrid instead)"] = replace(best, name="abl_hybrid", retrieval="hybrid")
    if best.retrieval != "dense" and best.use_bm25:
        configs["- BM25"] = replace(best, name="abl_no_bm25", use_bm25=False)
    if best.query != "whole": configs["- decomposition"] = replace(best, name="abl_whole", query="whole")
    if best.index != "plain": configs["- multi-vector index"] = replace(best, name="abl_plain", index="plain")
    if best.outcome_boost: configs["- outcome boost"] = replace(best, name="abl_no_outcome", outcome_boost=False)
    if best.corrective: configs["- corrective loop"] = replace(best, name="abl_no_crag", corrective=False)
    return configs


def rag_ablation(limit, output=None):
    configs = retrieval_ablations()
    import rag.retriever as R
    out = {}
    for label, cfg in configs.items():
        rs = []
        for p in PERSONAS:
            orig = R.variants
            R.variants = lambda cfg=cfg: {cfg.name: cfg}
            try: rs.append(evaluate(p, cfg.name, sample(dev(p), limit)))
            finally: R.variants = orig
            if output:
                save(output, {"complete": False, "rag": {**out, label: {"rows": rs}}})
        summary = {k: round(mean(r[k] for r in rs), 4) for k in ("recall@5", "mrr", "ndcg@10")}
        summary["refusal_accuracy"] = mean(r["refusal_accuracy"] for r in rs if r["refusal_accuracy"] is not None)
        out[label] = {**summary, "rows": rs}
        print(f"{label:24s} {summary}")
    return out


async def graph_ablation(n, output=None):
    app = mount_gigsim()
    out = {}
    headers = {"Authorization": f"Bearer {get_settings().gigsim_token}", "X-Account": "verification-ablation"}
    jobs = [(p, r["job"]["job_id"]) for p in PERSONAS
            for r in sample([r for r in dev(p) if r["gold"]["bid"] and r["gold"]["kind"] == "normal"], n)]
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://gigsim", headers=headers) as client:
        for verify in (True, False):
            label = "verification on" if verify else "verification off"
            rows = []
            out[label] = {"rows": rows}
            for p, job_id in jobs:
                row = {"persona": p, "job_id": job_id, "at_gate": False}
                try:
                    async with asyncio.timeout(180):
                        v = await run_to_gate(job_id, p, verify=verify)
                    row.update(at_gate=v["_at_gate"], latency_s=v["_latency_s"],
                               decision=(v.get("decision") or {}).get("action"), usage=v.get("usage", []))
                    if row["at_gate"]:
                        draft = v["draft"]
                        evidence = [{"id": key, "text": value.get("text", ""), "skills": value.get("skills", [])}
                                    for key, value in v.get("evidence", {}).items()]
                        answers = [answer["answer"] for answer in draft.get("screening_answers", [])]
                        texts = [draft["cover_letter"], *answers]
                        claims = claim_verifier.summarize([claim for text in texts for claim in claim_verifier.verify_text(text, evidence)])
                        response = await client.post("/eval/score", json={"job_id": job_id, "cover_letter": texts[0],
                                                     "bid_amount": v["price"]["bid_amount"], "screening_answers": answers})
                        row.update(claims=claims, proposal=draft["cover_letter"], evidence_ids=draft.get("evidence_ids", []),
                                   simulator=response.json() if response.is_success else None,
                                   simulator_http_status=response.status_code)
                except Exception as exc:
                    row["error"] = type(exc).__name__
                rows.append(row)
                if output:
                    save(output, {"complete": False, "graph": out})
            drafts = [row for row in rows if "claims" in row]
            unsupported = sum(row["claims"]["unsupported"] for row in drafts)
            claims = sum(row["claims"]["total_claims"] for row in drafts)
            sims = [row["simulator"] for row in drafts if row["simulator"] is not None]
            out[label].update(n=len(rows), drafts=len(drafts), claims=claims, unsupported_reaching_human=unsupported,
                              rate=round(unsupported / claims, 4) if claims else None,
                              simulator_scored=len(sims), simulated_reply_rate=mean(s["replied"] for s in sims) if sims else None)
    print({arm: {key: value for key, value in result.items() if key != "rows"} for arm, result in out.items()})
    return out


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--limit", type=int, default=100); ap.add_argument("--graph-jobs", type=int, default=15); ap.add_argument("--output", default="ablation"); ap.add_argument("--graph-only", action="store_true"); a = ap.parse_args()
    result = {} if a.graph_only else {"rag": rag_ablation(a.limit, a.output)}
    if a.graph_jobs:
        result["graph"] = asyncio.run(graph_ablation(a.graph_jobs, a.output if a.graph_only else None))
    save(a.output, {"complete": True, **result})


if __name__ == "__main__":
    main()
