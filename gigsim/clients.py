"""Simulated clients. Each job has hidden preferences; a proposal is scored against them and a
seeded draw decides viewed / replied / interview / hired. Deterministic per (job, account), so
two proposal strategies can be compared on the same jobs with common random numbers.

Deviation from the brief (documented in docs/DATA_CARD.md): the decision is a transparent
rule-based scorer with seeded noise rather than an LLM, so outcome evals are repeatable and free.
"""
from __future__ import annotations

import hashlib
import math
import re

GENERIC = re.compile(r"^\W*(dear (hiring manager|sir|madam|client)|i am writing to|i hope this (message|email) finds|hello,? i am an? (expert|passionate|experienced)|hi there!? i have read|greetings)", re.I)
CONTACT = re.compile(r"([\w.+-]+@[\w-]+\.[\w.]+|\+?\d[\d ()-]{8,}\d|telegram|whatsapp|skype|t\.me/|wa\.me/)", re.I)
GUARANTEE = re.compile(r"\b(guarantee[ds]?|100% (success|satisfaction)|risk[- ]free)\b", re.I)


def _u(*parts: str) -> float:
    return int(hashlib.sha256("|".join(parts).encode()).hexdigest()[:12], 16) / 16**12


def _mentions(text: str, skill: str, lexicon: dict) -> bool:
    names = [skill] + lexicon.get(skill, {}).get("aliases", [])
    return any(re.search(r"(?<![\w])" + re.escape(n.lower()) + r"(?![\w])", text) for n in names)


def score_proposal(job: dict, hidden: dict, client: dict, cover_letter: str, bid: float, answers: list[str], lexicon: dict, account: str = "eval") -> dict:
    prefs = hidden.get("prefs", {})
    text = cover_letter.lower()
    words = len(cover_letter.split())
    must = prefs.get("must_have_skills", [])
    m = sum(_mentions(text, s, lexicon) for s in must) / max(len(must), 1)
    ceiling = prefs.get("budget_ceiling", 1e9)
    price_ok = 1.0 if bid <= ceiling else max(0.0, 1 - (bid - ceiling) / max(ceiling, 1) * 2)
    generic = bool(GENERIC.search(cover_letter.strip())) and prefs.get("dislikes_generic_opening", True)
    title_words = {w for w in re.findall(r"[a-z]{4,}", job["title"].lower())} | {job.get("client_industry", "").lower()}
    specific = min(1.0, sum(w in text for w in title_words if w) / 3)
    numbers = bool(re.search(r"\d+(\.\d+)?\s?(%|x|ms|k|hours|days|weeks|minutes)", text)) or not prefs.get("wants_numbers", False)
    len_ok = 70 <= words <= 320
    qs = job.get("screening_questions", [])
    screening = 1.0 if not qs else sum(1 for a in answers[: len(qs)] if len(a.split()) >= 8) / len(qs)
    violation = bool(CONTACT.search(cover_letter)) or bool(GUARANTEE.search(cover_letter))
    z = -2.6 + 2.3 * m + 0.9 * price_ok + 0.8 * specific + 0.5 * numbers - 1.3 * generic + 0.4 * len_ok + 0.4 * screening
    p_reply = (1 / (1 + math.exp(-z))) * prefs.get("responsiveness", 0.8)
    if violation:
        p_reply *= 0.15
    scam = hidden.get("kind") == "scam"
    if scam:
        p_reply = 0.95  # scam "clients" always answer -- and ask to go off-platform
    u = _u(job["job_id"], account)
    replied = u < p_reply
    interview = (not scam) and u < p_reply * 0.6
    hired = (not scam) and u < p_reply * (0.2 + 0.35 * m)
    return {"viewed": _u(job["job_id"], account, "view") < 0.9 or replied, "replied": replied, "interview": interview, "hired": hired,
            "p_reply": round(p_reply, 4), "policy_violation": violation,
            "features": {"must_have": round(m, 2), "price_ok": round(price_ok, 2), "generic_opening": generic, "specific": round(specific, 2),
                         "numbers": numbers, "length_ok": len_ok, "screening": round(screening, 2)}}
