"""Outcome evaluation on GigSim's simulated clients (R&D question D + signature extension X2).

For each job the persona should bid on, we draft the proposal through the full graph under each
condition and score it against that job's hidden client preferences with GigSim's /eval/score.
Scoring is deterministic per (job, account), so conditions are compared on the SAME jobs with
common random numbers (a paired design); we report mean P(reply), the realised reply rate,
the paired difference with a bootstrap 95% CI, and an exact sign test.

Conditions:
  generic         -- a fixed, well-written but generic cover letter (what a template tool sends)
  evidence_first  -- GigBid, opening with the most relevant past project
  question_first  -- GigBid, opening with a question about the client's situation (X2 arm)

    python -m evals.runners.gigsim_outcomes [--per-persona 25]
"""
from __future__ import annotations

import argparse
import asyncio

import httpx

from agent.settings import get_settings
from evals.runners.common import (
    PERSONAS,
    bootstrap_ci,
    dev,
    mean,
    mount_gigsim,
    profile,
    run_to_gate,
    save,
    sign_test_p,
)

GENERIC = ("Dear Hiring Manager, I am writing to express my interest in your project. I am a passionate and experienced freelancer with strong skills in this area "
           "and a track record of delivering high quality work on time. I have read your job description carefully and I am confident I am the perfect fit. "
           "I communicate clearly, I meet deadlines, and I always go the extra mile for my clients. I would love to discuss how I can help you reach your goals. "
           "Please feel free to message me so we can get started.")


def compare_arms(rows, a, b):
    probability_diffs = [r[a]["p_reply"] - r[b]["p_reply"] for r in rows]
    wins = sum(d > 1e-9 for d in probability_diffs)
    losses = sum(d < -1e-9 for d in probability_diffs)
    reply_diffs = [int(r[a]["replied"]) - int(r[b]["replied"]) for r in rows]
    reply_wins, reply_losses = reply_diffs.count(1), reply_diffs.count(-1)
    return {"n_pairs": len(rows), "mean_diff_p_reply": mean(probability_diffs),
            "ci95": bootstrap_ci(probability_diffs), "wins": wins, "losses": losses,
            "sign_test_p": sign_test_p(wins, losses),
            "observed_reply_rate_difference": mean(reply_diffs),
            "observed_reply_rate_difference_ci95": bootstrap_ci(reply_diffs),
            "observed_reply_wins": reply_wins, "observed_reply_losses": reply_losses,
            "exact_paired_reply_p": sign_test_p(reply_wins, reply_losses)}


async def run(per: int) -> dict:
    app = mount_gigsim()
    rows = []
    headers = {"Authorization": f"Bearer {get_settings().gigsim_token}", "X-Account": "eval"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://gigsim", headers=headers) as c:
        async def score(job_id, letter, bid, answers):
            return (await c.post("/eval/score", json={"job_id": job_id, "cover_letter": letter, "bid_amount": bid, "screening_answers": answers})).json()
        for p in PERSONAS:
            jobs = [r for r in dev(p) if r["gold"]["bid"] and r["gold"]["kind"] == "normal"][:per]
            for r in jobs:
                jid = r["job"]["job_id"]; row = {"persona": p, "job_id": jid}
                for strat in ("evidence_first", "question_first"):
                    v = await run_to_gate(jid, p, user={**profile(p), "strategy": strat})
                    if not v["_at_gate"]: row[strat] = None; continue
                    d, price = v["draft"], v["price"]
                    s = await score(jid, d["cover_letter"], price["bid_amount"], [a["answer"] for a in d.get("screening_answers", [])])
                    row[strat] = {"p_reply": s["p_reply"], "replied": s["replied"], "hired": s["hired"], "violation": s["policy_violation"], "bid": price["bid_amount"]}
                bid = (row.get("evidence_first") or {}).get("bid") or (r["job"]["budget"].get("max") or 100)
                g = await score(jid, GENERIC, bid, ["I can do this." for _ in r["job"].get("screening_questions", [])])
                row["generic"] = {"p_reply": g["p_reply"], "replied": g["replied"], "hired": g["hired"], "violation": g["policy_violation"], "bid": bid}
                rows.append(row)
            print(p, "done")
    ok = [r for r in rows if r.get("evidence_first") and r.get("question_first")]
    arms = {a: {"n": len(ok), "mean_p_reply": mean(r[a]["p_reply"] for r in ok), "reply_rate": mean(r[a]["replied"] for r in ok), "hire_rate": mean(r[a]["hired"] for r in ok),
                "policy_violations": sum(r[a]["violation"] for r in ok)} for a in ("generic", "evidence_first", "question_first")}

    res = {"arms": arms, "evidence_first_vs_generic": compare_arms(ok, "evidence_first", "generic"),
           "question_first_vs_evidence_first": compare_arms(ok, "question_first", "evidence_first"), "rows": rows}
    print({k: v for k, v in res.items() if k != "rows"})
    return res


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--per-persona", type=int, default=25); a = ap.parse_args()
    res = asyncio.run(run(a.per_persona))
    save("gigsim_outcomes", res)
    save("experiment_ab", {"experiment": "X2 opening strategy", **{k: res[k] for k in ("arms", "question_first_vs_evidence_first")}})


if __name__ == "__main__":
    main()
