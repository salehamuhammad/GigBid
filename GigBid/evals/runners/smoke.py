"""CI smoke eval: a small, fast slice with hard failure thresholds. Exit 1 if any is broken.

    python -m evals.runners.smoke --jobs 30
"""
from __future__ import annotations

import argparse
import asyncio
import sys

from evals.runners.common import PERSONAS, dev, mount_gigsim, run_to_gate, sample
from evals.runners.rag_eval import evaluate

THRESHOLDS = {"recall@5": 0.45, "scam_recall": 0.9, "unsupported_after": 0.0, "bid_precision": 0.6}


async def graph_slice(n):
    mount_gigsim()
    scams = skipped = bids = good_bids = unsupported = 0
    for p in PERSONAS:
        for r in sample(dev(p), n // len(PERSONAS), seed=21):
            if r["gold"]["kind"] == "duplicate": continue
            v = await run_to_gate(r["job"]["job_id"], p)
            act = (v.get("decision") or {}).get("action")
            if r["gold"]["kind"] == "scam": scams += 1; skipped += act == "skip"
            if act == "bid": bids += 1; good_bids += r["gold"]["bid"]
            unsupported += (v.get("verification") or {}).get("unsupported_after", 0)
    return {"scam_recall": skipped / scams if scams else 1.0, "bid_precision": good_bids / bids if bids else 1.0, "unsupported_after": unsupported}


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--jobs", type=int, default=30); a = ap.parse_args()
    rag = evaluate("ai_engineer", "best", sample(dev("ai_engineer"), 60))
    g = asyncio.run(graph_slice(a.jobs))
    got = {"recall@5": rag["recall@5"], **g}
    fails = [k for k, t in THRESHOLDS.items() if (got[k] > t if k == "unsupported_after" else got[k] < t)]
    for k, t in THRESHOLDS.items(): print(f"{'FAIL' if k in fails else 'ok  '} {k:18s} {got[k]:.3f}  (threshold {t})")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
