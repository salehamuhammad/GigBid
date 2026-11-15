"""Calibrated LLM judge (B4). Two steps:

1. python -m evals.runners.judge --export 30
   writes evals/datasets/judge_labels.csv with 30 drafted proposals. Fill the `human_overall`
   column yourself (1-5) BEFORE looking at the judge's scores.
2. MODEL_PROFILE=open GROQ_API_KEY=... python -m evals.runners.judge --score
   scores every row with agent/prompts/judge.md and reports Cohen's kappa (quadratic-weighted and
   unweighted) between you and the judge. Only report judge scores if kappa is acceptable.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import random
from pathlib import Path

from pydantic import BaseModel, Field

from agent.llm import get_llm
from evals.runners.common import PERSONAS, ROOT, dev, mount_gigsim, run_to_gate, save

CSV = ROOT / "evals" / "datasets" / "judge_labels.csv"


class Score(BaseModel):
    relevance: int = Field(ge=1, le=5)
    evidence: int = Field(ge=1, le=5)
    clarity: int = Field(ge=1, le=5)
    professionalism: int = Field(ge=1, le=5)
    overall: int = Field(ge=1, le=5)
    reason: str = ""


def kappa(a: list[int], b: list[int], weighted: bool) -> float:
    k = 5; n = len(a)
    if not n: return None
    obs = [[0] * k for _ in range(k)]
    for x, y in zip(a, b): obs[x - 1][y - 1] += 1
    ra, rb = [sum(r) for r in obs], [sum(obs[i][j] for i in range(k)) for j in range(k)]
    w = lambda i, j: ((i - j) ** 2 / (k - 1) ** 2) if weighted else float(i != j)
    po = sum(w(i, j) * obs[i][j] for i in range(k) for j in range(k)) / n
    pe = sum(w(i, j) * ra[i] * rb[j] for i in range(k) for j in range(k)) / n ** 2
    return round(1 - po / pe, 4) if pe else None


async def export(n):
    mount_gigsim()
    rows = []
    for p in PERSONAS:
        for r in [r for r in dev(p) if r["gold"]["bid"] and r["gold"]["kind"] == "normal"][: n // len(PERSONAS) + 1]:
            v = await run_to_gate(r["job"]["job_id"], p)
            if v["_at_gate"]: rows.append({"persona": p, "job_id": r["job"]["job_id"], "job_post": r["job"]["title"] + "\n" + r["job"]["description"], "proposal": v["draft"]["cover_letter"], "human_overall": ""})
    if not rows:
        raise SystemExit("No proposals reached approval; no review packet was written.")
    with open(CSV, "x", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows[:n])
    print(f"wrote {CSV}: label `human_overall` (1-5) yourself, then run --score")


def export_measured(files: list[Path], n: int):
    posts = {r["job"]["job_id"]: r["job"] for persona in PERSONAS for r in dev(persona)}
    candidates = {}
    for file in files:
        benchmark = json.loads(file.read_text(encoding="utf-8-sig"))
        for arm in ("react", "supervisor", "graph"):
            for row in benchmark.get(arm, {}).get("rows", []):
                letter, job_id = row.get("letter"), row["job_id"]
                if row.get("action") == "bid" and letter and job_id in posts:
                    candidates.setdefault((job_id, letter), {"file": file.name, "arm": arm})
    rng = random.Random(4016)
    keys = list(candidates)
    rng.shuffle(keys)
    if len(keys) < n:
        raise SystemExit(f"Only {len(keys)} distinct proposals available; need {n}.")
    ranked = keys[:n]
    by_job = {}
    for key in keys:
        by_job.setdefault(key[0], []).append(key)
    paired = [(options[0], options[1]) for options in by_job.values() if len(options) >= 2][:15]
    ids = {key: f"P{i:03}" for i, key in enumerate(dict.fromkeys(ranked + [key for pair in paired for key in pair]), 1)}
    with CSV.open("x", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=["proposal_id", "job_post", "proposal", "human_overall"])
        writer.writeheader()
        for key in ranked:
            job = posts[key[0]]
            writer.writerow({"proposal_id": ids[key], "job_post": job["title"] + "\n" + job["description"],
                             "proposal": key[1], "human_overall": ""})
    pairs_file = CSV.with_name("judge_pairwise_panel.csv")
    with pairs_file.open("x", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=["pair_id", "job_post", "proposal_a", "proposal_b", "choice", "reason"])
        writer.writeheader()
        for i, pair in enumerate(paired, 1):
            job = posts[pair[0][0]]
            writer.writerow({"pair_id": f"PAIR{i:02}", "job_post": job["title"] + "\n" + job["description"],
                             "proposal_a": pair[0][1], "proposal_b": pair[1][1], "choice": "", "reason": ""})
    save("judge_blinding_manifest", {"calibration": {ids[key]: candidates[key] | {"job_id": key[0]} for key in ranked},
                                    "pairs": [{"a": ids[a], "b": ids[b], "sources": [candidates[a], candidates[b]]}
                                              for a, b in paired]})
    print(f"Exported {n} blank human ratings and {len(paired)} blind pairs")


async def score(ai_only=False):
    llm = get_llm()
    if llm.offline: raise SystemExit("Needs a real model: set MODEL_PROFILE=open and GROQ_API_KEY.")
    with CSV.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    if len(rows) < 30:
        raise SystemExit("The calibrated study requires at least 30 proposals.")
    if not ai_only and any(r["human_overall"].strip() not in ("1", "2", "3", "4", "5") for r in rows):
        raise SystemExit("Enter a human rating from 1 to 5 on every row.")
    out = []
    for r in rows:
        s, usage = await llm.structured("judge", "judge", {"job_post": r["job_post"], "proposal": r["proposal"]}, Score, lambda: Score(relevance=3, evidence=3, clarity=3, professionalism=3, overall=3, reason="fallback"))
        out.append({**r, "judge": None if usage.get("model") == "heuristic-fallback" else s.model_dump(), "usage": usage})
    scored = [r for r in out if r["judge"] is not None]
    j = [r["judge"]["overall"] for r in scored]
    res = {"n": len(out), "model_scored": len(scored), "mean_judge": sum(j) / len(j) if j else None, "rows": out}
    if not ai_only:
        h = [int(r["human_overall"]) for r in scored]
        res.update(kappa=kappa(h, j, False), kappa_quadratic=kappa(h, j, True), mean_human=sum(h) / len(h) if h else None)
    print({k: v for k, v in res.items() if k != "rows"})
    save("judge_ai_only" if ai_only else "judge_calibration", res)


def main():
    ap = argparse.ArgumentParser()
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--export", type=int)
    mode.add_argument("--from-results", nargs="+", type=Path)
    mode.add_argument("--score", action="store_true")
    mode.add_argument("--ai-only", action="store_true")
    a = ap.parse_args()
    if a.from_results:
        export_measured(a.from_results, 30)
    else:
        asyncio.run(export(a.export) if a.export is not None else score(a.ai_only))


if __name__ == "__main__":
    main()
