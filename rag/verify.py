"""Claim verification (B3, R5). After drafting, the proposal is split into sentences, each
experience claim is checked against retrieved evidence and labelled

    supported | partly_supported | unsupported | not_a_claim

Unsupported claims are removed before the Critic sees the draft. The unsupported-claim rate is
reported before and after. Two checkers share this module:

  * `check_claim`   -- deterministic fact check (skills, numbers, named entities, years).
  * an LLM checker  -- agent/nodes/verifier.py; its verdict can never be *more* lenient than the
                       numeric rule here (a number that is in no evidence item is never "supported").
"""
from __future__ import annotations

import re

from agent.settings import get_settings
from rag.skills import extract_skills, lexicon

_SENT = re.compile(r"(?<=[.!?])\s+(?=[A-Z\"'(])|\n+")
_FIRST_PERSON = re.compile(r"\b(i|i've|i'm|we|we've|my|our)\b", re.I)
_PAST = re.compile(r"\b(built|shipped|delivered|led|designed|developed|implemented|created|deployed|trained|fine-tuned|migrated|reduced|cut|raised|increased|improved|"
                   r"worked|used|handled|ran|managed|automated|have (built|shipped|delivered|worked|used|experience)|experience|expert|years?|certified|specialis|specializ|track record)\b", re.I)
_FUTURE = re.compile(r"^\W*(i (can|could|will|would|'d|'ll)|i am happy|happy to|could you|can you|would you|let me know|looking forward|thank|best|regards|hi\b|hello|if you|"
                     r"here is how i would|my plan|first,? i would|i propose|i suggest|what |how |when |which |do you|are you|is the)", re.I)
_NEG = re.compile(r"\b(have not|haven't|has not|did not|didn't|not yet|no (client |production )?experience|never (used|built|shipped)|would not claim)\b", re.I)
_NUM = re.compile(r"(?<![\w.])\$?\d[\d,]*(?:\.\d+)?\s?(?:%|x|k|ms|m)?(?![\w])")
_YEARS = re.compile(r"\b(\d+)\+?\s*years?\b", re.I)
_ENTITY = re.compile(r"(?<!^)(?<![.!?]\s)\b([A-Z][a-zA-Z0-9]+(?:\s[A-Z][a-zA-Z0-9]+)*)\b")
_COMMON = {"I", "The", "A", "An", "In", "For", "My", "We", "It", "This", "That", "Your", "You", "RAG", "API", "SQL", "CI", "CD", "ML", "AI", "LLM", "KPI", "ETL", "UI", "UX", "SaaS", "CRM", "CV", "PDF", "USD"}


def split_sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENT.split(text or "") if s and s.strip()]


def is_claim(sentence: str) -> bool:
    """An experience claim: first person + past/achievement language, a number, or a named skill."""
    s = sentence.strip()
    if _NEG.search(s): return False                      # an honest "I have not done X" is not an experience claim
    if len(s.split()) < 4 or s.endswith("?") or _FUTURE.search(s):
        return bool(_YEARS.search(s)) and bool(_FIRST_PERSON.search(s))
    if not _FIRST_PERSON.search(s) and not re.search(r"\b(the|that|this) (project|system|model|dashboard|pipeline|app|work)\b", s, re.I):
        return False
    return bool(_PAST.search(s) or _NUM.search(s) or extract_skills(s))


def facts(sentence: str) -> dict:
    skills = extract_skills(sentence)
    nums = [re.sub(r"[\s,]", "", n).lower() for n in _NUM.findall(sentence)]
    nums = [n for n in nums if n.strip("$%xkm.") not in ("", "1", "2", "3")]          # ignore "2 weeks"-style small counts
    known = {w.lower() for s in lexicon() for w in [s, *lexicon()[s]]}
    ents = [e for e in _ENTITY.findall(sentence) if e not in _COMMON and e.lower() not in known and not any(e.lower() in k for k in known)]
    return {"skills": skills, "numbers": nums, "entities": ents, "years": _YEARS.findall(sentence)}


def _norm(text: str) -> str:
    return re.sub(r"[\s,]", "", (text or "").lower())


def check_claim(sentence: str, evidence: list[dict], cited: list[str] | None = None) -> dict:
    """evidence: [{id, text, skills}]. Returns {text, label, evidence_ids, reason}."""
    th = get_settings().get("rag", "verify")
    # a sentence the writer attached evidence to is a claim by construction, whatever its grammar
    if not is_claim(sentence) and not (cited and (_NUM.search(sentence) or extract_skills(sentence)) and not _NEG.search(sentence)):
        return {"text": sentence, "label": "not_a_claim", "evidence_ids": [], "reason": ""}
    f = facts(sentence)
    total = len(f["skills"]) + len(f["numbers"]) + len(f["entities"]) + len(f["years"])
    order = sorted(evidence, key=lambda e: (e["id"] not in (cited or []),))
    best = (0.0, None, [])
    for e in order:
        text, compact = (e.get("text") or "").lower(), _norm(e.get("text"))
        have = set(e.get("skills") or []) | set(extract_skills(e.get("text") or ""))
        missing = [s for s in f["skills"] if s not in have]
        missing += [n for n in f["numbers"] if n not in compact]
        missing += [x for x in f["entities"] if x.lower() not in text]
        missing += [f"{y} years" for y in f["years"] if not re.search(rf"\b{y}\+?\s*years?\b", text)]
        cov = 1 - len(missing) / total if total else 0.0
        if cov > best[0] or best[1] is None: best = (cov, e["id"], missing)
    cov, eid, missing = best
    if total == 0:
        # no checkable fact: accept as partly supported only if it cites evidence or clearly paraphrases one item
        from rag.skills import tokenize
        toks = set(tokenize(sentence))
        cited_ok = [c for c in (cited or []) if any(e["id"] == c for e in evidence)]
        ov = max(((len(toks & set(tokenize(e.get("text") or ""))) / max(len(toks), 1), e["id"]) for e in evidence), default=(0.0, None))
        if cited_ok or ov[0] >= 0.6:
            return {"text": sentence, "label": "partly_supported", "evidence_ids": cited_ok[:2] or [ov[1]], "reason": "general experience claim; no checkable fact stated"}
        return {"text": sentence, "label": "unsupported", "evidence_ids": [], "reason": "experience claim with no evidence behind it"}
    # a number, employer or tenure that appears in no evidence item is invented, whatever else matches
    hard = any(m for m in missing if m not in f["skills"])
    label = "supported" if cov >= th["supported"] and not hard else "partly_supported" if cov >= th["partial"] and not (hard and cov < 0.6) else "unsupported"
    return {"text": sentence, "label": label, "evidence_ids": [eid] if eid and label != "unsupported" else [],
            "reason": "all stated facts found in evidence" if not missing else "not found in evidence: " + ", ".join(map(str, missing[:4]))}


def verify_text(text: str, evidence: list[dict], citations: dict[str, list[str]] | None = None) -> list[dict]:
    return [check_claim(s, evidence, (citations or {}).get(s)) for s in split_sentences(text)]


def remove_unsupported(text: str, checks: list[dict]) -> tuple[str, list[str]]:
    bad = [c["text"] for c in checks if c["label"] == "unsupported"]
    out = text
    for b in bad: out = out.replace(b, "")
    out = re.sub(r"[ \t]{2,}", " ", out); out = re.sub(r"\n{3,}", "\n\n", out); out = re.sub(r" +\n", "\n", out)
    return out.strip(), bad


def summarize(checks: list[dict]) -> dict:
    claims = [c for c in checks if c["label"] != "not_a_claim"]
    return {"total_claims": len(claims), "unsupported": sum(c["label"] == "unsupported" for c in claims),
            "partly": sum(c["label"] == "partly_supported" for c in claims), "supported": sum(c["label"] == "supported" for c in claims)}
