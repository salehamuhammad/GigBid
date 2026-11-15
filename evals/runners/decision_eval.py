"""Decision and draft quality through the whole bid graph (R&D question A/C inputs, E5 budgets).

Per persona, on a stratified sample of the dev set:
  bid precision / recall / F1 vs the gold `bid` label, scam recall, false-bid rate on scams,
  duplicate handling, unsupported-claim rate before and after verification, critic loops,
  words, latency p50/p95, tokens and USD per job (from the usage the nodes report).

    python -m evals.runners.decision_eval [--per-persona 45]
"""
from __future__ import annotations

import argparse
import asyncio
import random

from evals.runners.common import PERSONAS, dev, mean, mount_gigsim, pctl, run_to_gate, save


def stratified(rows, n, seed=5):
    rng = random.Random(seed)
    kinds = {}
    for r in rows: kinds.setdefault(r["gold"]["kind"], []).append(r)
    out = []
    share = {"normal": 0.55, "scam": 0.15, "injection": 0.12, "lowball": 0.1, "duplicate": 0.08}
    for k, frac in share.items():
        pool = kinds.get(k, []); out += rng.sample(pool, min(len(pool), max(1, round(n * frac))))
    return out


async def run(per_persona: int) -> dict:
    mount_gigsim()
    rows_out = []
    for p in PERSONAS:
        for r in stratified(dev(p), per_persona):
            g = r["gold"]
            v = await run_to_gate(r["job"]["job_id"], p)
            action = (v.get("decision") or {}).get("action", "none")
            ver = v.get("verification") or {}
            usage = v.get("usage", [])
            rows_out.append({"persona": p, "job_id": r["job"]["job_id"], "kind": g["kind"], "gold_bid": g["bid"], "action": action, "drafted": v["_at_gate"],
                             "unsupported_before": ver.get("unsupported_before", 0), "unsupported_after": ver.get("unsupported_after", 0), "claims": ver.get("total_claims", 0),
                             "revisions": sum(1 for c in v.get("critiques", []) if c.get("sent_back")), "words": len(((v.get("draft") or {}).get("cover_letter") or "").split()),
                             "latency_s": round(v["_latency_s"], 3), "tokens": sum(u.get("input_tokens", 0) + u.get("output_tokens", 0) for u in usage),
                             "cost_usd": sum(u.get("cost_usd", 0) for u in usage), "status": v.get("status"),
                             "price_in_band": _in_band((v.get("price") or {}).get("bid_amount"), g) if v["_at_gate"] else None})
        print(p, "done", len([x for x in rows_out if x["persona"] == p]))
    return summarize(rows_out)


def _in_band(bid, gold) -> bool | None:
    """Gold fair band: hourly -> the category's rate band; fixed -> hours x rate band x 0.8 (scripts/generate_data.py)."""
    if bid is None or not gold.get("price_band"): return None
    lo, hi = gold["price_band"]
    return bool(lo * 0.9 <= bid <= hi * 1.1)


def summarize(rows):
    def block(rs):
        # "duplicate" rows: the scout de-dups by content before the graph runs, so the graph is not asked to judge them here
        judged = [r for r in rs if r["kind"] != "duplicate"]
        tp = sum(r["action"] == "bid" and r["gold_bid"] for r in judged); fp = sum(r["action"] == "bid" and not r["gold_bid"] for r in judged)
        fn = sum(r["action"] != "bid" and r["gold_bid"] for r in judged)
        prec, rec = (tp / (tp + fp) if tp + fp else 0.0), (tp / (tp + fn) if tp + fn else 0.0)
        scams = [r for r in judged if r["kind"] == "scam"]
        drafts = [r for r in judged if r["drafted"]]
        claims = sum(r["claims"] for r in drafts) or 1
        return {"n": len(judged), "bid_precision": round(prec, 3), "bid_recall": round(rec, 3), "bid_f1": round(2 * prec * rec / (prec + rec), 3) if prec + rec else 0.0,
                "scam_recall": round(mean(r["action"] == "skip" for r in scams), 3), "scam_false_bid": sum(r["action"] == "bid" for r in scams),
                "drafts": len(drafts), "unsupported_claim_rate_before": round(sum(r["unsupported_before"] for r in drafts) / claims, 4),
                "unsupported_claim_rate_after": round(sum(r["unsupported_after"] for r in drafts) / claims, 4), "mean_revisions": mean(r["revisions"] for r in drafts),
                "mean_words": mean(r["words"] for r in drafts), "price_in_fair_band": mean(r["price_in_band"] for r in drafts if r["price_in_band"] is not None), "latency_p50_s": round(pctl([r["latency_s"] for r in judged], .5), 3),
                "latency_p95_s": round(pctl([r["latency_s"] for r in judged], .95), 3), "latency_p95_s_drafted": round(pctl([r["latency_s"] for r in drafts], .95), 3),
                "tokens_per_job": mean(r["tokens"] for r in judged), "usd_per_job": round(mean(r["cost_usd"] for r in judged), 6),
                "usd_per_proposal": round(sum(r["cost_usd"] for r in judged) / max(len(drafts), 1), 6)}
    return {"overall": block(rows), "by_persona": {p: block([r for r in rows if r["persona"] == p]) for p in PERSONAS}, "rows": rows}


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--per-persona", type=int, default=45); a = ap.parse_args()
    res = asyncio.run(run(a.per_persona))
    print({k: v for k, v in res["overall"].items()})
    save("decision", res)


if __name__ == "__main__":
    main()
