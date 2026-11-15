"""Fit Matcher: map every requirement to portfolio evidence; fit score with reasons (MCP: portfolio read).

Runs in parallel with the Job Analyst, so it splits requirements itself (bullets / sentences) and
asks the Portfolio server once per requirement. A requirement is only `covered` when the evidence
proves it; when retrieval refuses (corrective RAG) the requirement is recorded as uncovered and
the Writer is never given anything to claim."""
from __future__ import annotations

import asyncio

from pydantic import BaseModel, Field

from agent.handoffs import EvidenceItem, FitReport, RequirementMatch
from agent.runtime import Node, node
from rag.retriever import heuristic_requirements
from rag.skills import extract_skills, tokenize


class Judgement(BaseModel):
    requirement: str
    covered: bool
    strength: float = Field(ge=0, le=1)


class MatchOutput(BaseModel):
    matches: list[Judgement]


def heuristic_strength(requirement: str, evidence: list[dict]) -> float:
    """Skill named in the requirement and tagged on the evidence -> 1.0. No named skill: token overlap with the best snippet."""
    if not evidence: return 0.0
    skills = extract_skills(requirement)
    if skills:
        best = max(len(set(skills) & set(e["skills"])) / len(skills) for e in evidence)
        return round(best, 2)
    q = set(tokenize(requirement))
    if not q: return 0.0
    return round(min(1.0, max(len(q & set(tokenize(e["snippet"] + " " + e["title"]))) / len(q) for e in evidence) * 1.5), 2)


@node("matcher")
async def matcher(n: Node) -> dict:
    job = n.state["job"]
    reqs = heuristic_requirements(job.get("description", "")) or [job.get("title", "")]
    results = await asyncio.gather(*[n.tool("matcher", "portfolio.search_evidence", {"requirement": r, "k": 3}) for r in reqs])
    skills = await n.tool("matcher", "portfolio.list_skills", {})
    have = {s["skill"] for s in skills.get("skills", [])}
    pairs = [{"requirement": r, "evidence": [] if res.get("refused") else res.get("evidence", [])} for r, res in zip(reqs, results)]

    def fallback() -> MatchOutput:
        return MatchOutput(matches=[Judgement(requirement=p["requirement"], strength=(s := heuristic_strength(p["requirement"], p["evidence"])), covered=s >= 0.5) for p in pairs])

    brief = [{"requirement": p["requirement"], "evidence": [{"id": e["id"], "title": e["title"], "skills": e["skills"], "snippet": e["snippet"][:220]} for e in p["evidence"]]} for p in pairs]
    judged = await n.llm("matcher", "matcher", {"pairs": brief}, MatchOutput, fallback)
    by_req = {j.requirement: j for j in judged.matches}
    matrix = []
    for i, p in enumerate(pairs):
        j = by_req.get(p["requirement"]) or (judged.matches[i] if i < len(judged.matches) else Judgement(requirement=p["requirement"], covered=False, strength=0))
        ok = j.covered and bool(p["evidence"])          # no evidence -> never covered, whatever the model says
        matrix.append(RequirementMatch(requirement=p["requirement"], covered=ok, strength=j.strength if ok else min(j.strength, 0.4) if p["evidence"] else 0.0,
                                       evidence=[EvidenceItem(**e) for e in p["evidence"]] if p["evidence"] else []))
    needed = extract_skills(job.get("title", "") + "\n" + job.get("description", ""))
    score = round(sum(m.strength for m in matrix) / max(len(matrix), 1), 3)
    ev_ids = list(dict.fromkeys(e.id for m in matrix if m.covered for e in m.evidence[:2]))
    fit = FitReport(score=score, matrix=matrix, matched_skills=[s for s in needed if s in have], missing_skills=[s for s in needed if s not in have], evidence_ids=ev_ids,
                    reasons=[f"{sum(m.covered for m in matrix)}/{len(matrix)} requirements proven by portfolio evidence"] +
                            ([f"no evidence for: {', '.join(m.requirement[:50] for m in matrix if not m.covered)[:200]}"] if any(not m.covered for m in matrix) else []),
                    retrieval_refused=all(r.get("refused") for r in results) if results else True)
    phrasing = [e for r in results for e in r.get("phrasing_examples", [])][:3]
    return {"analyses": {"fit": fit.model_dump(), "phrasing": phrasing}, "_summary": f"fit {score:.2f}; {sum(m.covered for m in matrix)}/{len(matrix)} requirements covered"}
