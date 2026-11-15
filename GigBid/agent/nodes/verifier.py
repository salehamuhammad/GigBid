"""Claim verification node (B3): label every claim, remove unsupported ones before the Critic
sees the draft, and record the unsupported-claim rate before and after (MCP: portfolio read)."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from agent.handoffs import Claim, VerificationReport
from agent.runtime import Node, node
from rag import verify as V


class Check(BaseModel):
    index: int
    label: Literal["supported", "partly_supported", "unsupported"]
    evidence_id: str | None = None
    reason: str = ""


class VerifyOutput(BaseModel):
    checks: list[Check] = Field(default_factory=list)


ORDER = {"unsupported": 0, "partly_supported": 1, "supported": 2}


@node("verifier")
async def verifier(n: Node) -> dict:
    draft = dict(n.state["draft"])
    for eid in draft.get("evidence_ids", []):
        if eid not in (n.state.get("evidence") or {}):
            n.state.setdefault("evidence", {})[eid] = await n.tool("verifier", "portfolio.get_case_study", {"id": eid})
    ev = [{"id": k, "text": (v.get("text", "") + "\n" + v.get("title", "") + "\n" + v.get("client_industry", "") + "\n" + v.get("code", "")), "skills": v.get("skills", [])}
          for k, v in (n.state.get("evidence") or {}).items()]
    cites = {c["text"]: c.get("evidence_ids", []) for c in draft.get("claims", [])}
    texts = [draft["cover_letter"]] + [a["answer"] for a in draft.get("screening_answers", [])]
    checks = [c for t in texts for c in V.verify_text(t, ev, cites)]
    claims = [c for c in checks if c["label"] != "not_a_claim"]
    if claims and not n.ctx.llm.offline:
        def fallback() -> VerifyOutput: return VerifyOutput(checks=[Check(index=i, label=c["label"], evidence_id=(c["evidence_ids"] or [None])[0], reason=c["reason"]) for i, c in enumerate(claims)])
        res = await n.llm("verifier", "verifier", {"claims": "\n".join(f"{i}. {c['text']}" for i, c in enumerate(claims)),
                                                    "evidence": "\n\n".join(f"[{e['id']}]\n{e['text'][:1500]}" for e in ev) or "NONE"}, VerifyOutput, fallback)
        valid = {e["id"] for e in ev}
        for ck in res.checks:
            if 0 <= ck.index < len(claims):
                c = claims[ck.index]
                # the model may be stricter than the fact check, never more lenient about facts that are in no evidence item
                hard = c["label"] == "unsupported" and "not found in evidence" in c["reason"]
                if not hard and ORDER[ck.label] != ORDER[c["label"]]:
                    c["label"], c["reason"] = ck.label, ck.reason or c["reason"]
                    c["evidence_ids"] = [ck.evidence_id] if ck.evidence_id in valid and ck.label != "unsupported" else c["evidence_ids"] if ck.label != "unsupported" else []
    before = sum(c["label"] == "unsupported" for c in claims)
    removed: list[str] = []
    if n.ctx.verify and before:
        draft["cover_letter"], removed = V.remove_unsupported(draft["cover_letter"], checks)
        for a in draft.get("screening_answers", []):
            a["answer"], r2 = V.remove_unsupported(a["answer"], checks); removed += r2
            if not a["answer"]: a["answer"] = "I do not have a finished project that proves this yet, so I would rather not claim it."
    after = 0 if n.ctx.verify else before
    kept = [Claim(text=c["text"], evidence_ids=c["evidence_ids"], label=c["label"], reason=c["reason"]) for c in checks if not (n.ctx.verify and c["label"] == "unsupported")]
    draft["claims"] = [c.model_dump() for c in kept]
    draft["evidence_ids"] = list(dict.fromkeys(e for c in kept for e in c.evidence_ids))
    rep = VerificationReport(claims=[Claim(text=c["text"], evidence_ids=c["evidence_ids"], label=c["label"], reason=c["reason"]) for c in claims], total_claims=len(claims),
                             unsupported_before=before, unsupported_after=after, removed=removed)
    return {"draft": draft, "verification": rep.model_dump(), "_summary": f"{len(claims)} claims: {before} unsupported before, {after} after"}
