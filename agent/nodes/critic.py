"""Critic: grounding, personalisation, length; sends the draft back with reasons, at most twice
(MCP: portfolio read -- it reads the same evidence the verifier used, already in state)."""
from __future__ import annotations

import re

from agent.guardrails import rules
from agent.handoffs import Critique
from agent.runtime import Node, node
from agent.settings import get_settings
from rag.skills import tokenize


def heuristic_critique(letter: str, job: dict, spec: dict, verification: dict) -> Critique:
    t = get_settings().cfg["thresholds"]
    words = len(letter.split())
    claims = verification.get("claims", [])
    live = [c for c in claims if c["label"] != "unsupported"]
    grounding = (sum(c["label"] == "supported" for c in live) + 0.5 * sum(c["label"] == "partly_supported" for c in live)) / len(live) if live else 0.0
    job_terms = set(tokenize(job.get("title", "") + " " + " ".join(spec.get("required_skills", [])) + " " + job.get("client_industry", "")))
    pers = min(1.0, len(job_terms & set(tokenize(letter))) / max(min(len(job_terms), 6), 1))
    generic = any(re.search(p, letter) for p in rules()["generic_phrases"])
    length_ok = t["proposal_min_words"] <= words <= t["proposal_max_words"]
    reasons, todo = [], []
    if not live: reasons.append("No grounded claim is left in the draft"); todo.append("Add at least one concrete past project from the evidence, with its result.")
    elif grounding < 0.7: reasons.append(f"Grounding {grounding:.2f}: some claims are only partly supported"); todo.append("Cut or tighten claims that go beyond what the cited evidence states.")
    if generic: reasons.append("Generic opening or filler phrase"); todo.append("Open with the most relevant past project, not a greeting or self-description.")
    if pers < 0.5: reasons.append(f"Personalisation {pers:.2f}: the letter barely mentions this job's own terms"); todo.append("Name the client's deliverable and the tools they asked for.")
    if words > t["proposal_max_words"]: reasons.append(f"{words} words, over the {t['proposal_max_words']} limit"); todo.append("Shorten: cut the second reference and the plan sentence.")
    if words < t["proposal_min_words"]: reasons.append(f"{words} words, under the {t['proposal_min_words']} minimum"); todo.append("Add one more concrete, evidenced detail or a first-milestone plan.")
    return Critique(verdict="revise" if todo else "approve", grounding=round(grounding, 2), personalisation=round(0.0 if generic else pers, 2), length_ok=length_ok, reasons=reasons, instructions=todo[:4])


@node("critic")
async def critic(n: Node) -> dict:
    st = n.state; draft, job, spec = st["draft"], st["job"], st["analyses"]["job_spec"]
    t, b = get_settings().cfg["thresholds"], get_settings().cfg["budgets"]
    rev = st.get("revisions", 0)
    base = heuristic_critique(draft["cover_letter"], job, spec, st.get("verification", {}))
    c = await n.llm("critic", "critic", {"revision": rev, "max_revisions": b["max_revisions"], "words": len(draft["cover_letter"].split()), "job_spec": spec,
                                         "claims": [{"text": x["text"], "label": x["label"], "reason": x.get("reason", "")} for x in st.get("verification", {}).get("claims", [])],
                                         "draft": draft["cover_letter"], "min_words": t["proposal_min_words"], "max_words": t["proposal_max_words"]}, Critique, lambda: base)
    c = c.model_copy(update={"length_ok": base.length_ok})                 # word count is arithmetic, not opinion
    if not base.length_ok and c.verdict == "approve": c = c.model_copy(update={"verdict": "revise", "reasons": c.reasons + base.reasons, "instructions": c.instructions + base.instructions})
    will_revise = c.verdict == "revise" and rev < b["max_revisions"]
    note = {**c.model_dump(), "revision": rev, "sent_back": will_revise}
    return {"critiques": [note], "revisions": rev + 1 if will_revise else rev,
            "_summary": f"{c.verdict}" + (f" -> back to writer ({rev + 1}/{b['max_revisions']})" if will_revise else " (limit reached, moving on)" if c.verdict == "revise" else "")}
