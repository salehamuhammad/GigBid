"""Compliance Guard: enforce the policy pack; remove contact details, guarantees and invented
claims; block with a reason the UI shows (MCP: none).

Rules are data: data/policy_pack/rules.yaml. `redact` rules are applied automatically and reported;
`block` rules stop the draft. Used for proposals and for outgoing client messages."""
from __future__ import annotations

import re

from pydantic import BaseModel, Field

from agent.guardrails import rules
from agent.handoffs import ComplianceVerdict, Violation
from agent.runtime import Node, node
from agent.settings import get_settings


class LLMVerdict(BaseModel):
    violations: list[Violation] = Field(default_factory=list)


def run_rules(text: str, max_chars: int | None = None, unsupported: int = 0) -> ComplianceVerdict:
    out, violations = text, []
    for rule in rules()["compliance_rules"]:
        for pat in rule["patterns"]:
            for m in list(re.finditer(pat, out)):
                violations.append(Violation(rule=rule["id"], severity=rule["severity"], excerpt=m.group(0).strip()[:160], description=rule["description"]))
            if rule["severity"] == "redact": out = re.sub(pat, "", out)
    if unsupported:
        violations.append(Violation(rule="unsupported_claim", severity="block", excerpt=f"{unsupported} claim(s)", description="Claims with no portfolio evidence are still in the text."))
    out = re.sub(r"[ \t]{2,}", " ", re.sub(r" +([.,!?])", r"\1", out)); out = re.sub(r"\n{3,}", "\n\n", out).strip()
    if max_chars and len(out) > max_chars:
        violations.append(Violation(rule="cover_letter_length", severity="block", excerpt=f"{len(out)} characters", description=f"The marketplace allows at most {max_chars} characters."))
    blocked = [v for v in violations if v.severity == "block"]
    status = "blocked" if blocked else "redacted" if any(v.severity == "redact" for v in violations) else "pass"
    return ComplianceVerdict(status=status, violations=violations, cleaned_text=out,
                             reason="; ".join(f"{v.rule}: {v.description}" for v in blocked) if blocked else ("Removed: " + ", ".join(sorted({v.rule for v in violations}))) if violations else "")


def policy_max_chars(policy: dict | None) -> int | None:
    p = policy or {}
    return (p.get("update") or {}).get("max_cover_letter_chars") or (p.get("proposal") or {}).get("max_cover_letter_chars")


async def check(n: Node, text: str, max_chars: int | None, unsupported: int = 0) -> ComplianceVerdict:
    v = run_rules(text, max_chars, unsupported)
    if not n.ctx.llm.offline and v.status != "blocked":
        pack = (get_settings().data_dir / "policy_pack" / "marketplace_policy.md").read_text()
        extra = await n.llm("compliance", "compliance", {"policy": pack, "text": v.cleaned_text}, LLMVerdict, lambda: LLMVerdict())
        cleaned = v.cleaned_text
        known = {r["id"] for r in rules()["compliance_rules"]}
        for x in extra.violations:
            if x.rule not in known or not x.excerpt or x.excerpt not in cleaned: continue      # must quote real text and cite a real rule
            if x.severity == "redact": cleaned = cleaned.replace(x.excerpt, "").strip()
            v.violations.append(x)
        blocked = [x for x in v.violations if x.severity == "block"]
        v = v.model_copy(update={"cleaned_text": cleaned, "status": "blocked" if blocked else "redacted" if v.violations else "pass",
                                 "reason": "; ".join(f"{x.rule}: {x.description or x.excerpt}" for x in blocked) or v.reason})
    return v


@node("compliance")
async def compliance(n: Node) -> dict:
    st = n.state; draft = dict(st["draft"])
    unsupported = st.get("verification", {}).get("unsupported_after", 0) if n.ctx.verify else 0
    v = await check(n, draft["cover_letter"], policy_max_chars(st.get("policy")), unsupported)
    draft["cover_letter"] = v.cleaned_text
    for a in draft.get("screening_answers", []):
        a["answer"] = run_rules(a["answer"]).cleaned_text
    out = {"draft": draft, "compliance": v.model_dump(), "_summary": v.status + (f": {v.reason[:100]}" if v.reason else "")}
    if v.status == "blocked": out["status"] = "blocked"
    return out
