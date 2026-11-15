"""Decision node: skip, watch or bid. Deterministic and config-driven on purpose -- every
threshold is in agent/config.yaml, the reasons are shown verbatim in the UI, and a platform
policy change means editing configuration, not prompts or code."""
from __future__ import annotations

from agent.handoffs import BidDecision
from agent.runtime import Node, node
from agent.settings import get_settings


def decide_rule(job: dict, user: dict, risk: dict, fit: dict) -> BidDecision:
    t = get_settings().cfg["thresholds"]
    b = job.get("budget") or {}
    reasons = []
    if job.get("duplicate_of"):
        return BidDecision(action="skip", reasons=[f"Duplicate of {job['duplicate_of']} (same text, new id)"], confidence=0.95)
    if risk.get("is_scam") or risk.get("score", 0) >= t["maximum_risk_score"]:
        return BidDecision(action="skip", reasons=[f"Risk {risk.get('score', 0):.2f} is above the limit {t['maximum_risk_score']}: {risk.get('explanation', '')[:200]}"], confidence=0.95)
    floor, min_project = user.get("floor_rate", 0), user.get("min_project", 0)
    if b.get("type") == "hourly" and (b.get("max") or 0) < floor:
        return BidDecision(action="skip", reasons=[f"Hourly budget tops out at ${b.get('max')}/h, below your floor of ${floor}/h"], confidence=0.9)
    if b.get("type") == "fixed":
        hours = job.get("est_hours") or 0
        if (b.get("max") or 0) < min_project:
            return BidDecision(action="skip", reasons=[f"Budget ${b.get('max')} is below your minimum project size ${min_project}"], confidence=0.9)
        if hours and (b.get("max") or 0) / hours < floor * 0.6:
            return BidDecision(action="skip", reasons=[f"Budget ${b.get('max')} for about {hours}h is ${b['max'] / hours:.0f}/h, far below your floor of ${floor}/h"], confidence=0.85)
    score = fit.get("score", 0)
    reasons += fit.get("reasons", [])
    if risk.get("injection_detected"): reasons.append("The post contained text aimed at AI tools; it was removed and ignored")
    if score < t["watch_fit_score"]:
        return BidDecision(action="skip", reasons=[f"Fit {score:.2f} is below {t['watch_fit_score']}"] + reasons, confidence=0.8)
    if score < t["minimum_fit_score"]:
        return BidDecision(action="watch", reasons=[f"Fit {score:.2f} is between {t['watch_fit_score']} and {t['minimum_fit_score']}: worth watching, not worth Connects yet"] + reasons, confidence=0.6)
    return BidDecision(action="bid", reasons=[f"Fit {score:.2f} meets the bar {t['minimum_fit_score']}; risk {risk.get('score', 0):.2f} is acceptable"] + reasons, confidence=min(0.95, 0.5 + score / 2))


@node("decide")
async def decide(n: Node) -> dict:
    a = n.state.get("analyses", {})
    missing = [k for k in ("job_spec", "risk", "fit") if k not in a]
    if missing:
        return {"status": "dead_letter", "errors": [f"decide: analysis missing: {missing}"]}
    d = decide_rule(n.state["job"], n.state.get("user", {}), a["risk"], a["fit"])
    status = {"skip": "skipped", "watch": "watch", "bid": "recommended"}[d.action]
    return {"decision": d.model_dump(), "status": status, "_summary": f"{d.action}: {d.reasons[0][:120]}"}
