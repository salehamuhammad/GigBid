"""R7 / C2: the ONLY code that decides what enters long-term memory.

Two memories, two explicit rules:

  STYLE memory   -- learned from the user's own edits to drafts. An edit is reduced to
                    patterns (cut_first_sentence, ban_phrase:<x>, shorten, cut_last_sentence).
                    A pattern is a *candidate* until it has been observed in
                    `memory.style_promote_after` DISTINCT drafts; only then is it promoted.
  OUTCOME memory -- per job category: proposals sent, replies, hires, by strategy and opening
                    style. A category's stats are promoted to a usable hint only after
                    `memory.outcome_min_samples` proposals with a known outcome.

Nothing else writes memory. In particular raw tool output, job text and client messages never
reach it: `sanitize` rejects anything that looks like an instruction and masks PII, and the
inputs here are the user's edit and a closed set of outcome labels.
"""
from __future__ import annotations

import difflib
import re

from agent.guardrails import mask_pii, scan_untrusted
from agent.settings import get_settings
from rag.verify import split_sentences

_STOP = set("the a an and or to of in for on with is are was were be it this that i my we our you your as at by from can will would have has".split())


def diff_edit(before: str, after: str) -> dict:
    """Word-level diff of a user edit, for the UI and for pattern extraction."""
    a, b = before.split(), after.split()
    removed, added = [], []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag in ("delete", "replace"): removed.append(" ".join(a[i1:i2]))
        if tag in ("insert", "replace"): added.append(" ".join(b[j1:j2]))
    return {"removed": removed, "added": added, "words_before": len(a), "words_after": len(b),
            "unified": "\n".join(difflib.unified_diff(split_sentences(before), split_sentences(after), "draft", "your edit", lineterm=""))}


def extract_edit_patterns(before: str, after: str) -> list[dict]:
    """Reduce one edit to reusable style patterns. Returns [{key, type, value, description}]."""
    out: list[dict] = []
    sb, sa = split_sentences(before), split_sentences(after)
    if not sb or before.strip() == after.strip(): return out
    norm = lambda s: re.sub(r"\W+", " ", s).strip().lower()
    after_n = {norm(s) for s in sa}
    if len(sb) > 1 and norm(sb[0]) not in after_n and (not sa or norm(sa[0]) == norm(sb[1])):
        out.append({"key": "cut_first_sentence", "type": "cut_first_sentence", "value": "", "description": "Always cut the first sentence"})
    if len(sb) > 1 and norm(sb[-1]) not in after_n and sa and norm(sa[-1]) == norm(sb[-2]):
        out.append({"key": "cut_last_sentence", "type": "cut_last_sentence", "value": "", "description": "Always cut the closing sentence"})
    d = diff_edit(before, after)
    if d["words_before"] and d["words_after"] <= 0.8 * d["words_before"]:
        out.append({"key": "shorten", "type": "shorten", "value": "0.8", "description": "Keep drafts about 20% shorter"})
    low_after = after.lower()
    for chunk in d["removed"]:
        words = [w for w in re.findall(r"[A-Za-z][A-Za-z'-]+", chunk.lower()) if w not in _STOP]
        if 1 <= len(words) <= 3:                       # a word or short phrase the user deleted and did not re-use
            phrase = " ".join(words)
            if len(phrase) >= 5 and phrase not in low_after:
                out.append({"key": f"ban_phrase:{phrase}", "type": "ban_phrase", "value": phrase, "description": f"Never say \"{phrase}\""})
    seen, uniq = set(), []
    for p in out:
        if p["key"] not in seen: seen.add(p["key"]); uniq.append(p)
    return uniq


def sanitize(text: str) -> str | None:
    """Gate for any free text entering memory. None means: refuse to store."""
    text = (text or "").strip()
    if not text or len(text) > get_settings().get("memory", "max_item_chars", default=160): return None
    if scan_untrusted(text)["flagged"]: return None
    return mask_pii(text)


def should_promote_style(candidate: dict) -> bool:
    """PROMOTION RULE (style): seen in N distinct drafts, and never reverted by the user."""
    n = get_settings().get("memory", "style_promote_after", default=3)
    return len(set(candidate.get("drafts", []))) >= n and not candidate.get("reverted", False)


def update_outcome_stats(stats: dict | None, obs: dict) -> dict:
    """obs = {category, strategy, opening_style, outcome in sent|viewed|replied|interview|hired|lost}. Counts only."""
    s = stats or {"category": obs["category"], "sent": 0, "replied": 0, "hired": 0, "by_strategy": {}}
    arm = s["by_strategy"].setdefault(obs.get("strategy") or "evidence_first", {"sent": 0, "replied": 0, "hired": 0})
    o = obs["outcome"]
    if o == "sent": s["sent"] += 1; arm["sent"] += 1
    if o in ("replied", "interview"): s["replied"] += 1 if not obs.get("already_replied") else 0; arm["replied"] += 1 if not obs.get("already_replied") else 0
    if o == "hired": s["hired"] += 1; arm["hired"] += 1
    return s


def should_promote_outcome(stats: dict) -> bool:
    """PROMOTION RULE (outcome): enough proposals in the category to say anything at all."""
    return stats.get("sent", 0) >= get_settings().get("memory", "outcome_min_samples", default=5)


def outcome_hint(stats: dict) -> dict:
    rate = lambda d: round(d["replied"] / d["sent"], 3) if d.get("sent") else 0.0
    arms = {k: rate(v) for k, v in stats["by_strategy"].items() if v["sent"] >= 2}
    best = max(arms, key=arms.get) if arms else None
    return {"category": stats["category"], "sent": stats["sent"], "reply_rate": rate(stats), "hire_rate": round(stats["hired"] / stats["sent"], 3) if stats["sent"] else 0.0,
            "best_strategy": best, "description": f"{stats['category']}: {stats['replied']}/{stats['sent']} replied" + (f"; '{best}' openings do best" if best else "")}


def apply_style_rules(text: str, rules: list[dict]) -> str:
    """Deterministically enforce promoted style rules on any draft (LLM-written or not)."""
    for r in rules:
        sents = split_sentences(text)
        if r["type"] == "cut_first_sentence" and len(sents) > 2: text = text.replace(sents[0], "", 1).strip()
        elif r["type"] == "cut_last_sentence" and len(sents) > 2: text = text[: text.rfind(sents[-1])].strip()
        elif r["type"] == "ban_phrase": text = re.sub(r"\b" + re.escape(r["value"]) + r"\b[ ,]*", "", text, flags=re.I)
    return re.sub(r" {2,}", " ", re.sub(r" +([.,!?])", r"\1", text)).strip()
