"""Failure analysis (report section 8): every dev job the graph got wrong, grouped into the
assignment's taxonomy, from evals/results/decision.json (+ injection.json).

    python -m evals.runners.failure_analysis   -> evals/results/failures.json and a printed table
"""
from __future__ import annotations

import json
from collections import Counter

from evals.runners.common import RESULTS, dev, save


def classify(row: dict, gold: dict) -> str | None:
    a = row["action"]
    if gold["kind"] == "scam" and a == "bid": return "compliance miss (scam bid)"
    if gold["bid"] and a != "bid":
        return "missed evidence (wrong skip)" if gold["evidence"] else "wrong skip"
    if not gold["bid"] and a == "bid": return "wrong bid"
    if row.get("unsupported_after"): return "unsupported claim"
    if row.get("price_in_band") is False: return "mispriced"
    return None


def main():
    d = json.loads((RESULTS / "decision.json").read_text())
    gold = {r["job"]["job_id"]: r["gold"] for p in ("ai_engineer", "fullstack_dev", "data_analyst") for r in dev(p)}
    fails = []
    for row in d["rows"]:
        if row["kind"] == "duplicate": continue
        c = classify(row, gold[row["job_id"]])
        if c: fails.append({"category": c, **{k: row[k] for k in ("persona", "job_id", "kind", "action", "gold_bid", "price_in_band") if k in row}})
    inj = RESULTS / "injection.json"
    if inj.exists():
        for r in json.loads(inj.read_text())["rows"]:
            if r["defences"] and r["exposed"]: fails.append({"category": "injection (reached model input)", "persona": r["persona"], "job_id": r["job_id"]})
    counts = Counter(f["category"] for f in fails)
    for k, v in counts.most_common(): print(f"{v:4d}  {k}")
    save("failures", {"counts": dict(counts), "failures": fails})


if __name__ == "__main__":
    main()
