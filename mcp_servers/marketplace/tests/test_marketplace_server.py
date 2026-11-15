"""Marketplace MCP server through an in-memory MCP client (A7)."""
import json

import pytest

from agent.mcp_client import ToolError, ToolNotAllowed
from agent.settings import get_settings


async def _job(toolbox):
    jobs = await toolbox.call("scout", "marketplace.search_jobs", {"query": "", "limit": 5})
    return jobs["jobs"][0]


async def test_read_tools(toolbox):
    j = await _job(toolbox)
    job = await toolbox.call("scout", "marketplace.get_job", {"job_id": j["job_id"]})
    assert job["title"] and job["connects"]["total"] >= job["connects_cost"]
    hist = await toolbox.call("risk", "marketplace.get_client_history", {"client_id": job["client_id"]})
    assert "payment_verified" in hist
    stats = await toolbox.call("pricing", "marketplace.get_market_stats", {"category": job["category"]})
    assert stats["n_jobs"] > 0


async def test_dry_run_sends_nothing_and_shows_cost(toolbox):
    j = await _job(toolbox)
    before = await toolbox.call("pricing", "marketplace.get_connects_balance", {})
    letter = "For a SaaS client I built a retrieval assistant over help-centre articles and measured the result. " * 2
    prev = await toolbox.call("gateway", "marketplace.create_proposal_draft", {"job_id": j["job_id"], "cover_letter": letter, "bid_amount": 500, "idempotency_key": "dry-run-key-1", "dry_run": True})
    assert prev["dry_run"] and prev["draft_id"] is None
    assert prev["would_send"]["cover_letter"] == letter and prev["connects"]["total"] > 0
    assert prev["balance_after"] == before["balance"] - prev["connects"]["total"]
    after = await toolbox.call("pricing", "marketplace.get_connects_balance", {})
    assert after["balance"] == before["balance"]


async def test_idempotent_submit_spends_connects_once(toolbox):
    j = await _job(toolbox)
    letter = "For a SaaS client I built a retrieval assistant over help-centre articles and measured the result. " * 2
    d1 = await toolbox.call("gateway", "marketplace.create_proposal_draft", {"job_id": j["job_id"], "cover_letter": letter, "bid_amount": 500, "idempotency_key": "draft-key-0001"})
    d2 = await toolbox.call("gateway", "marketplace.create_proposal_draft", {"job_id": j["job_id"], "cover_letter": letter, "bid_amount": 500, "idempotency_key": "draft-key-0001"})
    assert d1["draft_id"] == d2["draft_id"] and d2["idempotent_replay"]
    s1 = await toolbox.call("gateway", "marketplace.submit_proposal", {"draft_id": d1["draft_id"], "idempotency_key": "submit-key-0001"})
    s2 = await toolbox.call("gateway", "marketplace.submit_proposal", {"draft_id": d1["draft_id"], "idempotency_key": "submit-key-0001"})
    assert s1["proposal_id"] == s2["proposal_id"] and s2["idempotent_replay"]
    bal = await toolbox.call("pricing", "marketplace.get_connects_balance", {})
    assert bal["balance"] == 120 - s1["connects_spent"]


async def test_input_constraints_rejected(toolbox):
    with pytest.raises(ToolError):
        await toolbox.call("gateway", "marketplace.create_proposal_draft", {"job_id": "live-00001", "cover_letter": "too short", "bid_amount": -5, "idempotency_key": "k"})


async def test_allowlist_blocks_writes_for_read_agents(toolbox):
    with pytest.raises(ToolNotAllowed):
        await toolbox.call("scout", "marketplace.submit_proposal", {"draft_id": "dr-1", "idempotency_key": "submit-key-0002"})
    with pytest.raises(ToolNotAllowed):
        await toolbox.call("compliance", "marketplace.get_job", {"job_id": "x"})


async def test_audit_log_is_appended_with_trace_id(toolbox):
    await toolbox.call("pricing", "marketplace.get_connects_balance", {})
    path = get_settings().processed / "audit" / "marketplace_audit.jsonl"
    last = json.loads(path.read_text().splitlines()[-1])
    assert last["tool"] == "get_connects_balance" and last["trace_id"] == "trace-test" and last["user"] == toolbox.ident.user


async def test_write_annotations(toolbox):
    tools = {t["name"]: t for t in await toolbox.list_tools(("marketplace",))}
    assert tools["search_jobs"]["annotations"]["readOnlyHint"] is True
    assert tools["submit_proposal"]["annotations"] == {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": True, "openWorldHint": True}
    assert tools["create_proposal_draft"]["outputSchema"]["properties"]["would_send"]
    assert "idempotency_key" in tools["send_message"]["inputSchema"]["required"]
