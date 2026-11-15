"""Skill graph (V9, GraphRAG-style): skills, projects, client industries and outcomes as nodes.

Edges: project -uses-> skill, project -for-> industry, doc -describes-> project,
proposal -cites-> project (with outcome). A query is answered by walking from the skills and
industries it names to projects, then to the documents that describe those projects -- which is
how "have I done X for a client in Y industry?" gets a direct answer.
"""
from __future__ import annotations

from collections import defaultdict

from rag.schema import Doc
from rag.skills import extract_skills


class SkillGraph:
    def __init__(self, docs: list[Doc]):
        self.skill_projects: dict[str, set[str]] = defaultdict(set)
        self.industry_projects: dict[str, set[str]] = defaultdict(set)
        self.project_docs: dict[str, list[str]] = defaultdict(list)
        self.project_skills: dict[str, set[str]] = defaultdict(set)
        self.project_wins: dict[str, float] = defaultdict(float)
        for d in docs:
            proj = d.meta.get("project") or ""
            if not proj: continue
            if d.type == "proposal":
                self.project_wins[proj] += {"won": 1.0, "replied": 0.5}.get(d.meta.get("outcome", ""), 0.0)
                continue
            self.project_docs[proj].append(d.id)
            for s in d.meta.get("skills") or []:
                self.skill_projects[s].add(proj); self.project_skills[proj].add(s)
            if d.meta.get("client_industry"):
                self.industry_projects[d.meta["client_industry"].lower()].add(proj)

    def query(self, text: str, n: int = 30) -> list[tuple[str, float]]:
        skills = extract_skills(text)
        low = text.lower()
        inds = [i for i in self.industry_projects if i and i in low]
        score: dict[str, float] = defaultdict(float)
        for s in skills:
            for p in self.skill_projects.get(s, ()): score[p] += 1.0
        for i in inds:
            for p in self.industry_projects[i]:
                if score.get(p): score[p] += 0.5       # industry only sharpens a skill match
        out = []
        for p, sc in score.items():
            for doc_id in self.project_docs.get(p, []):
                out.append((doc_id, sc / max(len(skills), 1)))
        return sorted(out, key=lambda x: -x[1])[:n]

    def stats(self) -> dict:
        return {"skills": len(self.skill_projects), "projects": len(self.project_docs), "industries": len(self.industry_projects)}
