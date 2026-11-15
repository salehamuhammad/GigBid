"""R&D question B: which RAG variant finds the right evidence, per persona.

Metrics against gold labels (dev set evidence = items whose skills cover >= 2 required skills):
Recall@5, MRR, nDCG@10, plus latency per query and, on jobs the persona should NOT bid on
(off-domain / no gold evidence), the share of queries where retrieval correctly returns
nothing or refuses ("refusal accuracy").

    python -m evals.runners.rag_eval [--limit 120] [--variants v0_naive,v2_hybrid,best]
"""
from __future__ import annotations

import argparse
import math
import time

from evals.runners.common import PERSONAS, dev, job_text, mean, pctl, sample, save
from rag.retriever import get_retriever, variants


def score(ids: list[str], gold: dict[str, int]) -> dict:
    ids = list(dict.fromkeys(ids))
    rec = len(set(ids[:5]) & set(gold)) / len(gold) if gold else 0.0
    mrr = next((1 / (i + 1) for i, d in enumerate(ids) if d in gold), 0.0)
    dcg = sum(gold.get(d, 0) / math.log2(i + 2) for i, d in enumerate(ids[:10]))
    idcg = sum(g / math.log2(i + 2) for i, g in enumerate(sorted(gold.values(), reverse=True)[:10]))
    return {"recall@5": rec, "mrr": mrr, "ndcg@10": dcg / idcg if idcg else 0.0}


def evaluate(persona: str, name: str, rows: list[dict]) -> dict:
    R = get_retriever(persona, name)
    pos = [r for r in rows if r["gold"]["evidence"] and r["gold"]["kind"] != "duplicate"]
    neg = [r for r in rows if not r["gold"]["evidence"] and r["gold"]["kind"] != "duplicate"]
    per, lat = [], []
    for r in pos:
        t = time.perf_counter(); res = R.retrieve(job_text(r["job"]), k=10); lat.append(time.perf_counter() - t)
        ids = [h.doc_id for h in res.hits]
        per.append({"job_id": r["job"]["job_id"], "category": r["gold"]["category"],
                    "retrieved": ids, "gold": r["gold"]["evidence"],
                    "latency_ms": round(1000 * lat[-1], 2), **score(ids, r["gold"]["evidence"])})
    refused = 0
    negatives = []
    for r in neg:
        res = R.retrieve(job_text(r["job"]), k=10)
        refused += res.refused or not res.hits
        negatives.append({"job_id": r["job"]["job_id"], "category": r["gold"]["category"],
                          "refused": res.refused or not res.hits})
    return {"persona": persona, "variant": name, "n_pos": len(pos), "n_neg": len(neg), **{k: round(mean(p[k] for p in per), 4) for k in ("recall@5", "mrr", "ndcg@10")},
            "refusal_accuracy": round(refused / len(neg), 4) if neg else None, "p50_ms": round(1000 * pctl(lat, 0.5), 1), "p95_ms": round(1000 * pctl(lat, 0.95), 1),
            "positives": per, "negatives": negatives}


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--limit", type=int, default=None); ap.add_argument("--variants", default=None); ap.add_argument("--output", default="rag"); a = ap.parse_args()
    names = a.variants.split(",") if a.variants else list(variants())
    out = []
    for p in PERSONAS:
        rows = sample(dev(p), a.limit)
        for n in names:
            r = evaluate(p, n, rows); out.append(r)
            print(f"{p:14s} {n:15s} R@5={r['recall@5']:.3f} MRR={r['mrr']:.3f} nDCG={r['ndcg@10']:.3f} refuse={r['refusal_accuracy']} p95={r['p95_ms']}ms")
    summary = {}
    for n in names:
        rs = [r for r in out if r["variant"] == n]
        positives = [item for r in rs for item in r["positives"]]
        negatives = [item for r in rs for item in r["negatives"]]
        by_category = {}
        for category in sorted({item["category"] for item in positives + negatives}):
            pos = [item for item in positives if item["category"] == category]
            neg = [item for item in negatives if item["category"] == category]
            by_category[category] = {
                "n_pos": len(pos), "n_neg": len(neg),
                **{k: mean(item[k] for item in pos) if pos else None for k in ("recall@5", "mrr", "ndcg@10")},
                "refusal_accuracy": mean(item["refused"] for item in neg) if neg else None,
            }
        summary[n] = {
            **{k: mean(r[k] for r in rs) for k in ("recall@5", "mrr", "ndcg@10")},
            "p95_ms": pctl([item["latency_ms"] for item in positives], .95),
            "refusal_accuracy": mean(item["refused"] for item in negatives) if negatives else None,
            "by_category": by_category,
        }
    save(a.output, {"rows": out, "summary": summary, "description": variants() and {n: variants()[n].description for n in names}})


if __name__ == "__main__":
    main()
