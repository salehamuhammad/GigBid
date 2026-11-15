"""Proposal Writer: cover letter and screening answers with evidence citations (MCP: portfolio read).

The writer returns sentences, each with the evidence ids it relies on. That structure is what
lets the UI show the evidence behind every claim on hover and lets the verifier check each one."""
from __future__ import annotations

import re

from pydantic import BaseModel, Field

from agent.guardrails import wrap_untrusted
from agent.handoffs import Claim, ProposalDraft, ScreeningAnswer
from agent.memory.promotion_rules import apply_style_rules
from agent.runtime import Node, node
from agent.settings import get_settings
from rag.skills import extract_skills
from rag.verify import split_sentences


class Sentence(BaseModel):
    text: str
    evidence_ids: list[str] = Field(default_factory=list)
    paragraph: int = 0


class WriterOutput(BaseModel):
    sentences: list[Sentence]
    screening_answers: list[ScreeningAnswer] = Field(default_factory=list)


def facts_of(item: dict) -> dict:
    """Pull the 'what' and the 'result' out of an evidence item's own text (no invention possible)."""
    text = item.get("text", "")
    ctx = re.search(r"##\s*Context\s*\n(.+?)(?:\n\n|\Z)", text, re.S)
    res = re.search(r"##\s*Result\s*\n(.+?)(?:\n\n|\Z)", text, re.S)
    what = re.sub(r"^.*?\bneeded\s+", "", ctx.group(1).strip().rstrip("."), flags=re.S) if ctx else ""
    result = re.sub(r"^The project\s+", "", res.group(1).strip().rstrip(".")) if res else ""
    if not what:
        body = [s for s in split_sentences(re.sub(r"[#*`>]", " ", text)) if len(s.split()) > 5]
        what = body[0].rstrip(".") if body else item.get("title", "")
    return {"what": what, "result": result, "title": item.get("title", ""), "industry": (item.get("client_industry") or "").lower()}


def heuristic_draft(job: dict, spec: dict, fit: dict, evidence: dict, strategy: str, critique: list[str], variant: int = 0) -> WriterOutput:
    """Template writer for the offline profile and as the last-resort fallback. It can only
    restate what an evidence item says, so it cannot fabricate; it is also plainer than a model."""
    covered = [m for m in fit.get("matrix", []) if m["covered"] and m["evidence"]]
    rank: dict[str, float] = {}
    for m in covered:
        for e in m["evidence"][:2]:
            if e["id"] in evidence and evidence[e["id"]].get("type") in ("case_study", "upload"):
                rank[e["id"]] = rank.get(e["id"], 0) + m["strength"]
    need_skills = extract_skills(job.get("title", "") + "\n" + job.get("description", ""))
    for k in rank: rank[k] += len(set(evidence[k].get("skills", [])) & set(need_skills))     # prefer the project that covers the most of what is asked
    order = sorted(rank, key=lambda k: -rank[k])
    if variant and len(order) > 1: order = order[1:] + order[:1]
    title = job.get("title", "your project")
    S: list[Sentence] = []
    shorten = any("short" in c.lower() or "length" in c.lower() or "cut" in c.lower() for c in critique)
    if not order:
        S.append(Sentence(text=f"I read your post about {title.lower()} and want to be straightforward: my portfolio has no finished project that proves the main requirements.", paragraph=0))
        S.append(Sentence(text="If the scope is flexible I would rather start with a small paid milestone so you can judge the work itself.", paragraph=1))
        S.append(Sentence(text="Which part of the project matters most to you in the first two weeks?", paragraph=1))
        return WriterOutput(sentences=S)
    e1 = evidence[order[0]]; f1 = facts_of(e1)
    ind = f"{'an' if f1['industry'][:1] in 'aeiou' else 'a'} {f1['industry']} client" if f1["industry"] else "a client"
    first_req = (spec.get("requirements") or [title])[0].rstrip(".")
    if strategy == "question_first":
        S.append(Sentence(text=f"One question before a plan for {title.lower()}: is the harder part on your side \"{first_req[:90].lower()}\", or getting it into daily use?", paragraph=0))
        S.append(Sentence(text=f"I ask because I delivered {f1['what']} for {ind}.", evidence_ids=[e1["id"]], paragraph=0))
    else:
        S.append(Sentence(text=f"Your project, {title.lower()}, is close to work I delivered for {ind}: {f1['what']}.", evidence_ids=[e1["id"]], paragraph=0))
    if f1["result"]:
        S.append(Sentence(text=f"That project {f1['result']}.", evidence_ids=[e1["id"]], paragraph=0))
    used = set(extract_skills(" ".join(s.text for s in S)))
    s1 = [s for s in e1.get("skills", []) if s in need_skills][:4]
    if s1:
        S.append(Sentence(text=f"I built it with {', '.join(s1)}, which you also list.", evidence_ids=[e1["id"]], paragraph=1)); used |= set(s1)
    for eid in order[1: 2 if shorten else 3]:
        e = evidence[eid]; f = facts_of(e)
        sk = [s for s in e.get("skills", []) if s in need_skills and s not in used][:3] or [s for s in e.get("skills", []) if s in need_skills][:2]
        if not sk: continue
        used |= set(sk)
        S.append(Sentence(text=f"For {', '.join(sk)}, a second reference is {f['title']}" + (f", which {f['result']}." if f["result"] and not shorten else "."), evidence_ids=[eid], paragraph=1))
    gaps = [s for s in fit.get("missing_skills", [])][:2]
    if gaps:
        S.append(Sentence(text=f"I have not used {' or '.join(gaps)} on a client project yet, so I would not claim it; I would plan extra time for that part.", paragraph=1))
    if not shorten:
        S.append(Sentence(text="For your project I would begin with a short, fixed-scope first milestone so you can judge the approach before committing to the rest.", paragraph=2))
    S.append(Sentence(text="Could you share a sample of the data or the current setup so I can confirm the scope?", paragraph=2))
    answers = []
    for q in job.get("screening_questions", []):
        ans = f"The closest example is {f1['title']}: I delivered {f1['what']}" + (f", and it {f1['result']}." if f1["result"] else ".")
        if re.search(r"first week|approach|start", q, re.I): ans += " I would spend the first days confirming scope and data access, then deliver a small working slice."
        answers.append(ScreeningAnswer(question=q, answer=ans, evidence_ids=[e1["id"]]))
    return WriterOutput(sentences=S, screening_answers=answers)


def assemble(out: WriterOutput) -> tuple[str, list[Claim]]:
    paras: dict[int, list[str]] = {}
    for s in out.sentences: paras.setdefault(s.paragraph, []).append(s.text.strip())
    letter = "\n\n".join(" ".join(v) for _, v in sorted(paras.items()))
    return letter, [Claim(text=s.text.strip(), evidence_ids=s.evidence_ids) for s in out.sentences]


@node("writer")
async def writer(n: Node) -> dict:
    st = n.state; job, a, user = st["job"], st["analyses"], st.get("user", {})
    fit, spec, t = a["fit"], a["job_spec"], get_settings().cfg["thresholds"]
    ids = fit.get("evidence_ids", [])[:6]
    evidence = dict(st.get("evidence") or {})
    for eid in ids:
        if eid not in evidence:
            evidence[eid] = await n.tool("writer", "portfolio.get_case_study", {"id": eid})
    revision = st.get("revisions", 0)
    critique = (st.get("critiques") or [{}])[-1].get("instructions", []) if revision else []
    regen = (st.get("approval") or {}) if (st.get("approval") or {}).get("action") == "regenerate" else None
    if regen: critique = [f"Rewrite paragraph {regen.get('paragraph', 0) + 1} with different wording and, if possible, a different supporting project. Keep every other paragraph word for word."]
    strategy = user.get("strategy") or "evidence_first"
    memory = st.get("memory") or {}
    style = memory.get("style", [])
    variables = {"strategy": strategy, "style_rules": [r["description"] for r in style] or "none yet", "outcome_hint": (memory.get("outcome") or {}).get(job.get("category", ""), {}).get("description", "no data yet"),
                 "critique": critique or "none", "bid": st.get("price", {}).get("bid_amount"), "job_spec": spec,
                 "matrix": [{"requirement": m["requirement"], "covered": m["covered"], "evidence_ids": [e["id"] for e in m["evidence"][:2]]} for m in fit.get("matrix", [])],
                 "evidence": "\n\n".join(f"[{eid}] {e.get('title')} (skills: {', '.join(e.get('skills', []))})\n{e.get('text', '')[:1400]}" for eid, e in evidence.items() if eid in ids) or "NONE - do not claim experience",
                 "phrasing": [p.get("snippet", "")[:200] for p in a.get("phrasing", [])], "job_post": wrap_untrusted(job.get("description", "")),
                 "min_words": t["proposal_min_words"], "max_words": t["proposal_max_words"]}
    variant = revision + len(st.get("approvals") or [])
    out = await n.llm("writer", "writer", variables, WriterOutput, lambda: heuristic_draft(job, spec, fit, {k: v for k, v in evidence.items() if k in ids}, strategy, critique, variant))
    valid = set(evidence)
    for s in out.sentences: s.evidence_ids = [e for e in s.evidence_ids if e in valid]      # a cited id that does not exist is dropped, never trusted
    letter, claims = assemble(out)
    letter = apply_style_rules(letter, style)
    kept = [c for c in claims if c.text in letter] or claims
    draft = ProposalDraft(job_id=job["job_id"], cover_letter=letter, claims=kept, screening_answers=out.screening_answers[: len(job.get("screening_questions", []))],
                          evidence_ids=list(dict.fromkeys(e for c in kept for e in c.evidence_ids)), strategy=strategy, revision=revision)
    return {"draft": draft.model_dump(), "evidence": evidence, "status": "drafting", "_summary": f"draft v{revision + 1}: {len(letter.split())} words, {len(draft.evidence_ids)} evidence items cited"}
