"""Rate limiting (R9): our limiter refuses beyond its budget, and a refusal parks the work
(ToolUnavailable -> job `queued`) instead of failing it."""
import time

import pytest

from agent.mcp_client import ToolUnavailable
from mcp_servers.common import RateLimiter
from mcp_servers.marketplace import server


async def test_limiter_allows_budget_then_reports_wait():
    rl = RateLimiter(3)
    assert [await rl.acquire("u", max_wait=0) for _ in range(3)] == [0.0, 0.0, 0.0]
    assert await rl.acquire("u", max_wait=0) > 50                       # 4th call in the same minute: wait about a minute
    assert await rl.acquire("other-user", max_wait=0) == 0.0            # budgets are per user


async def test_rate_limited_tool_call_parks_the_work(toolbox, monkeypatch):
    rl = RateLimiter(1)
    rl.calls[toolbox.ident.user].append(time.monotonic())               # budget already used
    monkeypatch.setattr(server, "_LIMITER", rl)
    with pytest.raises(ToolUnavailable, match="rate limited"):
        await toolbox.call("pricing", "marketplace.get_connects_balance", {})
