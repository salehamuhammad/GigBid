"""Reproducible Kaggle -> GigSim pricing-history importer.

Run from the GigBid project root:
    python -m scripts.prepare_kaggle --max-per-category 400 --seed 7

Only use source CSVs whose reuse terms you have reviewed.
Real rows go into historical pricing statistics, NEVER into evaluation gold labels.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import re
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from scripts.persona_defs import CATEGORIES, OFF_DOMAIN, SKILLS

ROOT = Path(__file__).resolve().parents[1]
ALIASES = {
    "title": ("title", "job_title"),
    "description": ("description", "job_description", "snippet"),
    "url": ("link", "url", "job_url"),
    "budget": ("budget", "fixed_budget", "amount"),
    "hourly_low": ("hourly_low", "hourly_min", "min_hourly"),
    "hourly_high": ("hourly_high", "hourly_max", "max_hourly"),
    "is_hourly": ("is_hourly", "hourly"),
    "country": ("country", "client_country", "location"),
    "published": ("published_date", "date_posted", "posted", "created_at"),
}
MONEY = re.compile(r"^(?:USD\s*)?\$?\s*(\d+(?:,\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?)\s*(?:USD)?$", re.I)


def money(value: object) -> float | None:
    """Accept clear USD amounts; reject ranges, '10k', other currencies, and invalid values."""
    if value is None:
        return None
    match = MONEY.fullmatch(str(value).strip())
    if not match:
        return None
    try:
        amount = Decimal(match.group(1).replace(",", ""))
        if not amount.is_finite() or amount <= 0:
            return None
        return float(amount)
    except (InvalidOperation, ValueError, OverflowError):
        return None


def hourly_flag(value: object) -> bool | None:
    s = str(value or "").strip().lower()
    if s in {"true", "1", "yes", "y", "hourly"}:
        return True
    if s in {"false", "0", "no", "n", "fixed", "fixed-price"}:
        return False
    return None


def normalize(value: object) -> str:
    return " ".join(str(value or "").casefold().split())


def canonical_url(value: object) -> str | None:
    try:
        s = urlsplit(str(value or "").strip())
        if s.scheme.lower() not in {"http", "https"} or not s.netloc:
            return None
        return urlunsplit(("", s.netloc.lower(), s.path.rstrip("/"), "", ""))
    except ValueError:
        return None


def patterns() -> dict[str, re.Pattern]:
    result = {}
    for category, (_, pool, _) in CATEGORIES.items():
        if category in OFF_DOMAIN:
            continue
        names = [
            name for skill in pool
            for name in (skill, *(SKILLS.get(skill, ([], "", ""))[0]))
            if len(name) > 2 and name.lower() not in
            {"python", "sql", "docker", "aws", "queries", "caching",
             "containers", "charts", "payments"}
        ]
        result[category] = re.compile(
            r"(?<![\w])(" + "|".join(re.escape(n) for n in sorted(set(names), key=len, reverse=True))
            + r")(?![\w])", re.I
        )
    return result


def choose_budget(row: dict, cols: dict) -> dict | None:
    get = lambda key: money(row.get(cols[key])) if cols[key] else None
    low, high, fixed = get("hourly_low"), get("hourly_high"), get("budget")
    kind = hourly_flag(row.get(cols["is_hourly"])) if cols["is_hourly"] else None
    if kind is True:
        if low is not None and high is not None and 3 <= low <= high <= 400:
            return {"type": "hourly", "min": low, "max": high, "currency": "USD"}
        return None
    if kind is False:
        if fixed is not None and 20 <= fixed <= 200_000:
            return {"type": "fixed", "min": fixed, "max": fixed, "currency": "USD"}
        return None
    # Unknown billing type: infer only when unambiguous.
    valid_hourly = low is not None and high is not None and 3 <= low <= high <= 400
    valid_fixed = fixed is not None and 20 <= fixed <= 200_000
    if valid_hourly == valid_fixed:
        return None
    if valid_hourly:
        return {"type": "hourly", "min": low, "max": high, "currency": "USD"}
    return {"type": "fixed", "min": fixed, "max": fixed, "currency": "USD"}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-per-category", type=int, default=400)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()
    if args.max_per_category < 1:
        parser.error("--max-per-category must be positive")
    files = sorted((ROOT / "data" / "raw").glob("*.csv"))
    if not files:
        parser.error("No CSV files in data/raw/")
    rng = random.Random(args.seed)
    regexes = patterns()
    seen_urls, seen_content = set(), set()
    counts, eligible_counts = Counter(), Counter()
    samples = defaultdict(list)
    source_hashes = {}
    csv.field_size_limit(10**8)

    for file in files:
        digest = hashlib.sha256()
        with file.open("rb") as raw:
            for block in iter(lambda: raw.read(1024 * 1024), b""):
                digest.update(block)
        source_hashes[file.name] = digest.hexdigest()

        with file.open("r", newline="", encoding="utf-8-sig", errors="replace") as stream:
            reader = csv.DictReader(stream)
            headers = {h.casefold().strip(): h for h in (reader.fieldnames or []) if h}
            cols = {key: next((headers[a] for a in aliases if a in headers), None)
                    for key, aliases in ALIASES.items()}
            print(f"{file.name}: column mapping = {cols}")
            if not cols["title"] or not cols["description"]:
                raise ValueError(f"{file.name}: required title/description columns missing")
            if not any(cols[k] for k in ("budget", "hourly_low", "hourly_high")):
                raise ValueError(f"{file.name}: budget columns missing")

            for i, row in enumerate(reader, 2):
                counts["rows_read"] += 1
                title = str(row.get(cols["title"]) or "").strip()
                description = str(row.get(cols["description"]) or "").strip()
                if not title or not description:
                    counts["missing_text"] += 1
                    continue
                budget = choose_budget(row, cols)
                if budget is None:
                    counts["invalid_or_ambiguous_price"] += 1
                    continue
                content_key = hashlib.sha256(
                    (normalize(title) + "\n" + normalize(description)).encode()
                ).hexdigest()
                url_key = canonical_url(row.get(cols["url"])) if cols["url"] else None
                if content_key in seen_content or (url_key and url_key in seen_urls):
                    counts["duplicate"] += 1
                    continue
                text = f"{title}\n{description}"
                hits = {category: len(pattern.findall(text))
                        for category, pattern in regexes.items()}
                category = max(hits, key=hits.get)
                if hits[category] == 0:
                    counts["out_of_domain"] += 1
                    continue

                # Mark eligible records as seen before sampling (dedupe across categories/files).
                seen_content.add(content_key)
                if url_key:
                    seen_urls.add(url_key)
                eligible_counts[category] += 1
                counts["eligible"] += 1
                identity = url_key or content_key
                job_id = "real-" + hashlib.sha256(identity.encode()).hexdigest()[:20]
                record = {
                    "job_id": job_id, "title": title[:200],
                    "description": text[:3000], "category": category,
                    "budget": budget,
                    "country": row.get(cols["country"]) if cols["country"] else None,
                    "posted_at": row.get(cols["published"]) if cols["published"] else None,
                    "est_hours": None,
                    "provenance": f"kaggle:{file.name}",
                }
                bucket = samples[category]
                n = eligible_counts[category]
                # Reservoir sampling avoids taking only the first 400 rows.
                if len(bucket) < args.max_per_category:
                    bucket.append(record)
                else:
                    j = rng.randrange(n)
                    if j < args.max_per_category:
                        bucket[j] = record

    output = [row for cat in sorted(samples) for row in samples[cat]]
    output.sort(key=lambda row: row["job_id"])
    dest = ROOT / "data" / "gigsim" / "jobs_historical_real.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    temp = dest.with_suffix(".json.tmp")
    temp.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(dest)

    audit = {
        "sources_sha256": source_hashes,
        "seed": args.seed,
        "max_per_category": args.max_per_category,
        "counts": dict(counts),
        "eligible_by_category": dict(sorted(eligible_counts.items())),
        "selected_by_category": dict(sorted(Counter(r["category"] for r in output).items())),
        "selected_total": len(output),
        "pricing_currency": "USD",
        "uses": "historical pricing statistics only; no gold labels or live stream",
        "caveats": [
            "Skills-based inclusion and per-category sampling are not representative of Upwork.",
            "USD is assumed because the CSV does not declare a currency field.",
            "No conversion of international currencies; verify the source documentation.",
            "Not deduplicated against synthetic historical jobs.",
            "URL and exact-normalized-text dedup may miss near-duplicate rewritten postings.",
        ],
    }
    report = ROOT / "data" / "gigsim" / "kaggle_import_audit.json"
    report.write_text(json.dumps(audit, indent=2), encoding="utf-8")
    print(f"Imported: {len(output)} -> {dest}")
    print(f"Eligible before sampling: {counts['eligible']}")
    print(f"Rejected reasons: {dict(counts)}")
    print(f"Sample sizes: {audit['selected_by_category']}")
    print(f"Audit: {report}")


if __name__ == "__main__":
    main()
