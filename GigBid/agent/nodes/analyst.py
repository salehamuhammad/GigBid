"""Job Analyst: extract a structured JobSpec (MCP: none)."""
from __future__ import annotations

from agent.guardrails import wrap_untrusted
from agent.handoffs import JobSpec
from agent.runtime import Node, node
from rag.retriever import heuristic_requirements
from rag.skills import extract_skills


def heuristic_jobspec(job: dict) -> JobSpec:
    desc = job.get("description", "")
    reqs = heuristic_requirements(desc)
    return JobSpec(job_id=job["job_id"], title=job.get("title", ""), summary=desc.strip().split("\n")[0][:240], deliverables=reqs[:5],
                   required_skills=extract_skills(job.get("title", "") + "\n" + desc), requirements=reqs)


@node("analyst")
async def analyst(n: Node) -> dict:
    job = n.state["job"]; b = job.get("budget") or {}
    spec = await n.llm("analyst", "analyst", {"job_id": job["job_id"], "title": job.get("title", ""), "budget": b, "screening_questions": job.get("screening_questions", []),
                                              "job_post": wrap_untrusted(job.get("description", ""))}, JobSpec, lambda: heuristic_jobspec(job))
    # Facts the marketplace already gave us are authoritative; the model only adds understanding.
    spec = spec.model_copy(update={"job_id": job["job_id"], "title": job.get("title", spec.title), "category": job.get("category", spec.category),
                                   "budget_type": b.get("type", "unknown"), "budget_min": b.get("min"), "budget_max": b.get("max"),
                                   "timeline_weeks": job.get("duration_weeks", spec.timeline_weeks), "screening_questions": job.get("screening_questions", []),
                                   "requirements": (spec.requirements or heuristic_requirements(job.get("description", "")))[:8]})
    return {"analyses": {"job_spec": spec.model_dump()}, "_summary": f"{len(spec.requirements)} requirements, {len(spec.required_skills)} skills"}
