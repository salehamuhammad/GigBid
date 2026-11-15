"""Risk Assessor: client quality from history; scams, free-work requests, off-platform asks and
injected instructions (MCP: marketplace read).

Signals and weights come from data/policy_pack/rules.yaml. The rule score is a floor: a model may
add flags and raise the score, but it can never talk a rule-detected red flag down."""
from __future__ import annotations

import re
from datetime import date

from agent.guardrails import rules, wrap_untrusted
from agent.handoffs import RiskFlag, RiskReport
from agent.runtime import Node, node
from agent.settings import get_settings


def rule_risk(job: dict, client: dict) -> RiskReport:
    r, text = rules(), job.get("description_raw") or job.get("description", "")
    flags, p_safe = [], 1.0
    for code, sig in r["risk_signals"].items():
        for pat in sig["patterns"]:
            m = re.search(pat, text)
            if m:
                flags.append(RiskFlag(code=code, severity="high" if sig["weight"] >= 0.4 else "medium", evidence=text[max(0, m.start() - 30): m.end() + 30].strip()[:160]))
                p_safe *= 1 - sig["weight"]; break
    cs, quality = r["client_signals"], 1.0
    if client:
        if not client.get("payment_verified"): flags.append(RiskFlag(code="payment_unverified", severity="medium", evidence="client payment method is not verified")); p_safe *= 1 - cs["payment_unverified"]; quality -= 0.35
        if not client.get("hires"): flags.append(RiskFlag(code="no_hire_history", severity="low", evidence="client has never hired")); p_safe *= 1 - cs["no_hire_history"]; quality -= 0.2
        if client.get("rating") and client["rating"] < cs["low_rating_below"]: flags.append(RiskFlag(code="low_client_rating", severity="low", evidence=f"rating {client['rating']}")); p_safe *= 1 - cs["low_rating"]; quality -= 0.2
        try:
            if (date.today() - date.fromisoformat(client.get("member_since", "2000-01-01"))).days < cs["new_account_days"]:
                flags.append(RiskFlag(code="new_account", severity="low", evidence=f"member since {client['member_since']}")); p_safe *= 1 - cs["new_account"]; quality -= 0.1
        except ValueError: pass
        quality += min(0.2, (client.get("hire_rate") or 0) * 0.2)
    if (job.get("injection") or {}).get("flagged"):
        flags.append(RiskFlag(code="prompt_injection", severity="medium", evidence=job["injection"]["matches"][0][:160])); p_safe *= 0.85
    b = job.get("budget") or {}
    if b.get("type") == "fixed" and not b.get("max"): flags.append(RiskFlag(code="zero_budget", severity="medium", evidence="fixed budget of 0")); p_safe *= 0.8
    score = round(1 - p_safe, 3)
    # A request that breaks platform policy (off-platform payment, unpaid work, upfront fees) is
    # disqualifying on its own: one such flag makes the job a scam regardless of the blended score.
    is_scam = any(f.severity == "high" for f in flags)
    if is_scam: score = max(score, get_settings().get("thresholds", "maximum_risk_score"))
    return RiskReport(score=score, level="high" if score >= 0.6 else "medium" if score >= 0.3 else "low", flags=flags, client_quality=round(max(0.0, min(1.0, quality)), 2),
                      is_scam=is_scam, injection_detected=bool((job.get("injection") or {}).get("flagged")),
                      explanation="; ".join(f"{f.code}: {f.evidence}" for f in flags[:4]) or "No risk signals; client history looks normal.")


@node("risk")
async def risk(n: Node) -> dict:
    job = n.state["job"]
    client = await n.tool("risk", "marketplace.get_client_history", {"client_id": job["client_id"]}) if job.get("client_id") else {}
    base = rule_risk(job, client)
    rep = await n.llm("risk", "risk", {"rule_flags": [f.model_dump() for f in base.flags], "client": {k: v for k, v in client.items() if k != "reviews_from_freelancers"},
                                       "job_post": wrap_untrusted(job.get("description", ""))}, RiskReport, lambda: base)
    if rep is not base:      # merge: rules are the floor
        codes = {f.code for f in base.flags}
        merged = base.flags + [f for f in rep.flags if f.code not in codes]
        score = max(base.score, rep.score if rep.is_scam or rep.flags else base.score)
        rep = rep.model_copy(update={"score": round(score, 3), "flags": merged, "client_quality": base.client_quality, "injection_detected": base.injection_detected or rep.injection_detected,
                                     "is_scam": base.is_scam or (rep.is_scam and score >= get_settings().get("thresholds", "maximum_risk_score")),
                                     "level": "high" if score >= 0.6 else "medium" if score >= 0.3 else "low"})
    return {"analyses": {"risk": rep.model_dump(), "client": client}, "_summary": f"risk {rep.score:.2f} ({rep.level})" + (", SCAM" if rep.is_scam else "")}
