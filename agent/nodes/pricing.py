"""Pricing Strategist: bid from market statistics, client spend and the user's floor; decide
whether the Connects cost is worth it (MCP: marketplace read).

Connects cost, the daily proposal cap and the cover-letter limit are READ from the marketplace
(job.connects, get_connects_balance, get_policy). The 2 Nov policy update changed all three and
needed no change here."""
from __future__ import annotations

from agent.handoffs import PriceQuote
from agent.runtime import Node, node
from agent.settings import get_settings


def quote(job: dict, user: dict, stats: dict, client: dict, balance: dict, reply_rate: float) -> PriceQuote:
    t = get_settings().cfg["thresholds"]
    b, floor, target = job.get("budget") or {}, float(user.get("floor_rate", 20)), float(user.get("target_rate", 40))
    why = []
    if b.get("type") == "hourly":
        m = stats.get("hourly_rate_usd") or {}
        lo, med, hi = m.get("p25"), m.get("median"), m.get("p75")
        want = min(target, med) if med else target
        bid = max(floor, min(want, b.get("max") or want))
        why.append(f"Hourly job: target ${target:.0f}/h" + (f", market median ${med:.0f}/h (n={m.get('n')})" if med else ", no market data") + f", client range ${b.get('min')}-${b.get('max')}/h -> ${bid:.0f}/h")
        value, kind = bid * (job.get("est_hours") or 20), "hourly"
    else:
        m = stats.get("fixed_usd_per_est_hour") or {}
        lo, med, hi = m.get("p25"), m.get("median"), m.get("p75")
        hours = job.get("est_hours") or max(5, round((b.get("max") or 500) / max(med or target, 1)))
        rate = max(floor, min(target, med or target))
        bid = rate * hours
        why.append(f"About {hours}h at ${rate:.0f}/h" + (f" (market median ${med:.0f}/h, p25-p75 ${lo:.0f}-${hi:.0f}, n={m.get('n')})" if med else " (no market data; using your target rate)"))
        cap = b.get("max")
        if cap and bid > cap * 1.05:
            new = max(floor * hours, cap)
            why.append(f"Client budget tops out at ${cap:.0f}: bid lowered from ${bid:.0f} to ${new:.0f}, never below floor ${floor:.0f}/h x {hours}h")
            bid = new
        spent, hires = client.get("total_spent_usd") or 0, client.get("hires") or 0
        if hires and spent / hires < bid * 0.4:
            why.append(f"Client's average spend per hire is ${spent / hires:.0f}, well under this bid: expect negotiation")
        bid, value, kind = round(bid, -1), bid, "fixed"
        lo, med, hi = (x * hours if x else None for x in (lo, med, hi))
    cost = (job.get("connects") or {}).get("total", job.get("connects_cost", 0))
    surcharge = (job.get("connects") or {}).get("surcharge", 0)
    ev = reply_rate * 0.3 * value                      # P(reply) x P(hire | reply) x contract value
    per_connect = ev / cost if cost else ev
    worth, bal = True, balance.get("balance")
    why.append(f"Connects: {cost}" + (f" (includes a {surcharge}-Connect crowded-job surcharge)" if surcharge else "") + f"; expected value ${ev:.0f} = ${per_connect:.1f} per Connect at a {reply_rate:.0%} reply rate")
    if per_connect < t["min_expected_value_per_connect_usd"]:
        worth = False; why.append(f"Below your minimum of ${t['min_expected_value_per_connect_usd']:.2f} expected value per Connect")
    if bal is not None and bal < cost:
        worth = False; why.append(f"Not enough Connects: balance {bal}, cost {cost}")
    left = user.get("connects_budget_week", 10**6) - user.get("connects_spent_week", 0)
    if left < cost:
        worth = False; why.append(f"Weekly Connects budget exhausted: {left} left, cost {cost}")
    cap = balance.get("daily_proposal_cap")
    if cap and (balance.get("proposals_today") or 0) >= cap:
        worth = False; why.append(f"Daily proposal cap reached ({cap} per day, platform policy)")
    return PriceQuote(bid_amount=max(bid, 1), bid_type=kind, floor=floor, market_low=lo, market_median=med, market_high=hi, connects_cost=cost, connects_balance=bal,
                      expected_value_usd=round(ev, 2), worth_connects=worth, rationale=why)


@node("pricing")
async def pricing(n: Node) -> dict:
    job, user, a = n.state["job"], n.state.get("user", {}), n.state.get("analyses", {})
    stats = await n.tool("pricing", "marketplace.get_market_stats", {"category": job.get("category") or "unknown"})
    balance = await n.tool("pricing", "marketplace.get_connects_balance", {})
    policy = await n.tool("pricing", "marketplace.get_policy", {})
    hint = (n.state.get("memory", {}).get("outcome") or {}).get(job.get("category", ""))
    rate = hint["reply_rate"] if hint and hint.get("sent", 0) >= 5 else get_settings().get("thresholds", "base_reply_rate")
    q = quote(job, user, stats, a.get("client", {}), balance, rate)
    out = {"price": q.model_dump(), "policy": policy, "_summary": f"${q.bid_amount:.0f} {q.bid_type}; {q.connects_cost} Connects; {'worth it' if q.worth_connects else 'NOT worth it'}"}
    if not q.worth_connects:
        out |= {"decision": {"action": "skip", "reasons": [r for r in q.rationale if "Connect" in r or "cap" in r][-2:], "confidence": 0.8}, "status": "skipped"}
    return out
