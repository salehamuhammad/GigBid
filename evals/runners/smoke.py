"""CI smoke eval: a small, fast slice with hard failure thresholds. Exit 1 if any is broken.

    python -m evals.runners.smoke --jobs 30
"""
from __future__ import annotations

import argparse
import asyncio
import sys

from agent.settings import get_settings
from evals.runners.common import PERSONAS, dev, mount_gigsim, run_to_gate, sample
from evals.runners.rag_eval import evaluate

THRESHOLDS = {"recall@5": 0.45, "scam_recall": 0.9, "unsupported_after": 0.0, "bid_precision": 0.6, "bid_f1": 0.6}


async def graph_slice(n):
    mount_gigsim()
    scams = skipped = bids = good_bids = gold_bids = unsupported = 0
    per_persona, remainder = divmod(n, len(PERSONAS))
    for i, p in enumerate(PERSONAS):
        count = per_persona + (i < remainder)
        eligible = [r for r in dev(p) if r["gold"]["kind"] != "duplicate"]
        for r in sample(eligible, count, seed=21):
            v = await run_to_gate(r["job"]["job_id"], p)
            act = (v.get("decision") or {}).get("action")
            gold_bids += r["gold"]["bid"]
            if r["gold"]["kind"] == "scam": scams += 1; skipped += act == "skip"
            if act == "bid": bids += 1; good_bids += r["gold"]["bid"]
            unsupported += (v.get("verification") or {}).get("unsupported_after", 0)
    return {
        "scam_recall": skipped / scams if scams else 1.0,
        "bid_precision": good_bids / bids if bids else 0.0,
        "bid_f1": 2 * good_bids / (bids + gold_bids) if bids + gold_bids else 0.0,
        "unsupported_after": unsupported,
    }


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--jobs", type=int, default=30); a = ap.parse_args()
    if a.jobs < len(PERSONAS):
        ap.error("--jobs must cover all personas")
    variant = get_settings().get("rag", "deployed_variant")
    rag = evaluate("ai_engineer", variant, sample(dev("ai_engineer"), 60))
    g = asyncio.run(graph_slice(a.jobs))
    got = {"recall@5": rag["recall@5"], **g}
    fails = [k for k, t in THRESHOLDS.items() if (got[k] > t if k == "unsupported_after" else got[k] < t)]
    for k, t in THRESHOLDS.items(): print(f"{'FAIL' if k in fails else 'ok  '} {k:18s} {got[k]:.3f}  (threshold {t})")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
