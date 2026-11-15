"""Portfolio tools (read-only): search_evidence, get_case_study, list_skills."""
from __future__ import annotations

import asyncio
from collections import Counter
from typing import Annotated, Literal

from mcp.server.fastmcp import Context, FastMCP
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from mcp_servers.common import Identity, identity
from rag.retriever import EVIDENCE_TYPES, get_retriever, owner_index

READ = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
EvidenceType = Literal["case_study", "repo", "review", "upload", "cv", "proposal"]


class EvidenceFilters(BaseModel):
    types: list[EvidenceType] | None = Field(default=None, description="Restrict to these evidence types. Default: case_study, repo, review, upload")
    skills: list[str] | None = Field(default=None, description="Keep only items tagged with at least one of these skills")
    client_industry: str | None = None
    outcome: str | None = Field(default=None, description="For past proposals: won | replied | ignored")
    after: str | None = Field(default=None, description="Keep items dated on or after YYYY-MM-DD")
    variant: str | None = Field(default=None, description="RAG variant to use (default: the deployed one)")


class Evidence(BaseModel):
    id: str
    type: str
    title: str
    source: str
    date: str
    outcome: str
    project: str = ""
    skills: list[str] = []
    snippet: str
    score: float


class SearchEvidenceResult(BaseModel):
    requirement: str
    evidence: list[Evidence]
    refused: bool = Field(default=False, description="True when retrieval found nothing strong enough: do NOT claim experience for this requirement")
    phrasing_examples: list[Evidence] = Field(default_factory=list, description="Past proposals that won or got a reply. Wording inspiration only -- never proof of experience")
    variant: str = ""


class CaseStudy(BaseModel):
    id: str
    type: str
    title: str
    text: str
    code: str = ""
    project: str = ""
    skills: list[str] = []
    date: str = ""
    client_industry: str = ""
    outcome: str = ""


class SkillsResult(BaseModel):
    skills: list[dict]
    total_items: int


def get_item(owner: str, item_id: str) -> CaseStudy:
    d = owner_index(owner).docs.get(item_id)
    if d is None:
        raise ValueError(f"No portfolio item with id '{item_id}'. Use search_evidence to find valid ids.")
    return CaseStudy(id=d.id, type=d.type, title=d.title, text=d.text, code=d.code[:4000], project=d.meta.get("project", ""), skills=d.meta.get("skills") or [],
                     date=d.meta.get("date", ""), client_industry=d.meta.get("client_industry", ""), outcome=d.meta.get("outcome", ""))


def search(owner: str, requirement: str, k: int = 5, filters: EvidenceFilters | None = None, requirements: list[str] | None = None) -> SearchEvidenceResult:
    f = filters or EvidenceFilters()
    r = get_retriever(owner, f.variant)
    types = tuple(f.types) if f.types else EVIDENCE_TYPES
    res = r.retrieve(requirement, requirements=requirements, k=max(k * 3, 10), types=types)
    def keep(it: dict) -> bool:
        return ((not f.skills or set(f.skills) & set(it["skills"])) and (not f.client_industry or f.client_industry.lower() == (r.ix.docs[it["id"]].meta.get("client_industry") or "").lower())
                and (not f.outcome or it["outcome"] == f.outcome) and (not f.after or (it["date"] or "0") >= f.after))
    items = [it for it in (r.item(h) for h in res.hits) if keep(it)][:k]
    return SearchEvidenceResult(requirement=requirement[:300], evidence=[Evidence(**i) for i in items], refused=res.refused and not items,
                                phrasing_examples=[Evidence(**r.item(h)) for h in res.phrasing], variant=r.cfg.name)


def register(mcp: FastMCP, default: Identity | None) -> None:
    @mcp.tool(annotations=READ, description="Find portfolio evidence that proves ONE requirement (a skill, deliverable or need). Returns ranked items with type, source, date and outcome. "
              "If `refused` is true there is no real evidence: do not claim that experience. Call once per requirement rather than pasting a whole job post.")
    async def search_evidence(ctx: Context, requirement: Annotated[str, Field(min_length=2, max_length=4000, description="One requirement in plain words, e.g. 'RAG chatbot over PDF documents'")],
                              k: Annotated[int, Field(ge=1, le=20)] = 5, filters: EvidenceFilters | None = None) -> SearchEvidenceResult:
        return await asyncio.to_thread(search, identity(ctx, default).owner, requirement, k, filters)

    @mcp.tool(annotations=READ, description="Load one full portfolio item by id (case study, repo with code, review, CV or past proposal). Use ids returned by search_evidence.")
    async def get_case_study(ctx: Context, id: Annotated[str, Field(min_length=3, max_length=120)]) -> CaseStudy:
        return get_item(identity(ctx, default).owner, id)

    @mcp.tool(annotations=READ, description="All skills the portfolio can prove, with how many projects back each one. Use to check quickly whether a skill is covered at all.")
    async def list_skills(ctx: Context) -> SkillsResult:
        ix = owner_index(identity(ctx, default).owner)
        c = Counter(s for d in ix.docs.values() if d.type in ("case_study", "repo", "upload") for s in (d.meta.get("skills") or []))
        return SkillsResult(skills=[{"skill": s, "items": n} for s, n in c.most_common()], total_items=len(ix.docs))
