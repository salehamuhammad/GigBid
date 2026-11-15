"""Merge REAL Upwork job postings from Kaggle into GigSim's historical job set.

    1. Download one or more of the datasets listed in docs/DATA_CARD.md and unzip the CSVs into data/raw/
    2. python -m scripts.prepare_kaggle [--max-per-category 400]

Reads every CSV in data/raw/, detects the columns it needs by name (title, description, budget,
hourly_low/hourly_high, is_hourly, country, published_date), keeps postings whose text names skills
from one of GigBid's job categories, and writes data/gigsim/jobs_historical_real.json. GigSim loads
that file next to the synthetic history, so `get_market_stats` (pricing) is then computed from real
budgets. Every row is labelled `"provenance": "kaggle:<file>"`; synthetic rows stay `"synthetic"`.

Real rows are used ONLY for market pricing statistics. They carry no client, no hidden
preferences and no gold labels, so they never enter the dev set or the live job stream.

NOTE: written against the published column lists of the asaniczka / ahmedmyalo datasets; the
column detection is tolerant, and the script prints what it mapped so you can check it.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter
from pathlib import Path

from scripts.persona_defs import CATEGORIES, OFF_DOMAIN, SKILLS

ROOT = Path(__file__).resolve().parents[1]
ALIASES = {"title": ["title", "job_title"], "description": ["description", "job_description", "snippet"], "budget": ["budget", "fixed_budget", "amount"],
           "hourly_low": ["hourly_low", "hourly_min", "min_hourly"], "hourly_high": ["hourly_high", "hourly_max", "max_hourly"], "is_hourly": ["is_hourly", "hourly"],
           "country": ["country", "client_country", "location"], "published": ["published_date", "date_posted", "posted", "created_at"]}


def _num(v) -> float | None:
    try:
        x = float(re.sub(r"[^\d.]", "", str(v)))
        return x if x > 0 else None
    except ValueError:
        return None


def _patterns() -> dict[str, re.Pattern]:
    out = {}
    for cat, (_, pool, _) in CATEGORIES.items():
        if cat in OFF_DOMAIN: continue
        names = [n for s in pool for n in [s, *(SKILLS.get(s, ([], "", ""))[0])] if len(n) > 2 and n.lower() not in ("python", "sql", "docker", "aws", "queries", "caching", "containers", "charts", "payments")]
        out[cat] = re.compile(r"(?<![\w])(" + "|".join(re.escape(n) for n in sorted(names, key=len, reverse=True)) + r")(?![\w])", re.I)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(); ap.add_argument("--max-per-category", type=int, default=400); a = ap.parse_args()
    files = sorted((ROOT / "data" / "raw").glob("*.csv"))
    if not files: sys.exit("No CSV files in data/raw/. Download a dataset from docs/DATA_CARD.md first.")
    pats, out, per = _patterns(), [], Counter()
    csv.field_size_limit(10**9)
    for f in files:
        with open(f, newline="", encoding="utf-8", errors="ignore") as fh:
            rd = csv.DictReader(fh)
            cols = {k: next((c for c in (rd.fieldnames or []) if c.lower().strip() in v), None) for k, v in ALIASES.items()}
            print(f"{f.name}: columns mapped -> {cols}")
            if not cols["title"]: print("  skipped: no title column"); continue
            for i, row in enumerate(rd):
                text = f"{row.get(cols['title']) or ''}\n{row.get(cols['description']) or '' if cols['description'] else ''}"
                hits = {c: len(p.findall(text)) for c, p in pats.items()}
                cat = max(hits, key=hits.get)
                if hits[cat] == 0 or per[cat] >= a.max_per_category: continue
                lo, hi, fixed = (_num(row.get(cols[k])) if cols[k] else None for k in ("hourly_low", "hourly_high", "budget"))
                if lo and hi and 3 <= lo <= hi <= 400: budget = {"type": "hourly", "min": lo, "max": hi, "currency": "USD"}
                elif fixed and 20 <= fixed <= 200_000: budget = {"type": "fixed", "min": fixed, "max": fixed, "currency": "USD"}
                else: continue
                per[cat] += 1
                out.append({"job_id": f"real-{f.stem[:12]}-{i}", "title": (row.get(cols["title"]) or "")[:200], "description": text[:3000], "category": cat, "budget": budget,
                            "country": row.get(cols["country"]) if cols["country"] else None, "posted_at": row.get(cols["published"]) if cols["published"] else None,
                            "est_hours": None, "provenance": f"kaggle:{f.name}"})
    dest = ROOT / "data" / "gigsim" / "jobs_historical_real.json"
    dest.write_text(json.dumps(out))
    print(f"wrote {len(out)} real postings to {dest}\nper category: {dict(per)}\nRestart GigSim to load them.")


if __name__ == "__main__":
    main()
