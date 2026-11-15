"""Live adapter: the official Upwork MCP server behind the same marketplace port (A4).

  * Connects with MultiServerMCPClient over Streamable HTTP using the user's OAuth access token
    (stored encrypted, see apps/api/auth/token_store.py; obtained in apps/api/auth/upwork_oauth.py).
  * Port methods are mapped onto Upwork's tools through `marketplace.upwork.tool_map` in
    agent/config.yaml and verified against list_tools() on first use. An unmapped or missing
    tool raises a clear MarketplaceError -- we never guess a tool or fall back to scraping.
  * Writes are DRAFTS only. `submit_proposal` does not submit: Upwork requires the user to
    confirm on the platform, and GigBid never bypasses that.
  * No browser automation, no session cookies, no page scraping.

STATUS: written against the published interface; not exercised against a real Upwork account
by the author of this file's first version. Run `python -m scripts.check_upwork` after
connecting your account and fix `tool_map` if Upwork's tool names differ.
"""
from __future__ import annotations

import json
import os
from typing import Any

from agent.marketplace_port import MarketplaceError, MarketplaceUnavailable
from agent.settings import get_settings


class UpworkLiveAdapter:
    name = "upwork"

    def __init__(self, account: str, trace_id: str = ""):
        cfg = get_settings().cfg["marketplace"]["upwork"]
        self.account, self.url, self.map, self.timeout = account, os.getenv("UPWORK_MCP_URL") or cfg["url"], cfg["tool_map"], get_settings().cfg["marketplace"]["timeout_s"]
        self._tools: set[str] | None = None

    def _client(self):
        from langchain_mcp_adapters.client import MultiServerMCPClient

        from apps.api.auth.token_store import get_access_token
        token = get_access_token(self.account, "upwork")
        if not token:
            raise MarketplaceError("Upwork is not connected for this user. Connect it in Settings -> Connected accounts.", 401)
        return MultiServerMCPClient({"upwork": {"transport": "streamable_http", "url": self.url, "headers": {"Authorization": f"Bearer {token}"}}})

    async def _call(self, method: str, args: dict[str, Any]) -> dict[str, Any]:
        tool = self.map.get(method)
        if not tool:
            raise MarketplaceError(f"'{method}' has no Upwork tool mapped in marketplace.upwork.tool_map", 501)
        try:
            async with self._client().session("upwork") as session:
                if self._tools is None:
                    self._tools = {t.name for t in (await session.list_tools()).tools}
                if tool not in self._tools:
                    raise MarketplaceError(f"Upwork MCP server has no tool '{tool}' (mapped from '{method}'). Available: {sorted(self._tools)[:25]}", 501)
                res = await session.call_tool(tool, {k: v for k, v in args.items() if v is not None})
        except MarketplaceError:
            raise
        except Exception as e:
            raise MarketplaceUnavailable(f"Upwork MCP unavailable: {type(e).__name__}") from e
        if res.isError:
            raise MarketplaceError(" ".join(getattr(c, "text", "") for c in res.content)[:300])
        if res.structuredContent: return dict(res.structuredContent)
        text = " ".join(getattr(c, "text", "") for c in res.content)
        try:
            out = json.loads(text); return out if isinstance(out, dict) else {"items": out}
        except Exception:
            return {"text": text}

    # ---- read
    async def search_jobs(self, query, category=None, limit=20, offset=0):
        r = await self._call("search_jobs", {"query": query, "limit": limit})
        return {"total": len(r.get("jobs", r.get("items", []))), "jobs": r.get("jobs", r.get("items", []))}
    async def get_job(self, job_id): return await self._call("get_job", {"job_id": job_id})
    async def get_client_history(self, client_id): return await self._call("get_client_history", {"client_id": client_id})
    async def get_connects_balance(self): return await self._call("get_connects_balance", {})
    async def get_market_stats(self, category):
        return {"category": category, "n_jobs": 0, "fixed_budget_usd": None, "hourly_rate_usd": None, "fixed_usd_per_est_hour": None,
                "provenance": ["unavailable in live mode: pricing falls back to the user's floor and the job's own budget"]}
    async def get_policy(self): return {"version": "upwork-live", "proposal": {"max_cover_letter_chars": 5000}, "update": {}}
    async def list_threads(self): return await self._call("list_messages", {})
    async def list_messages(self, thread_id): return await self._call("list_messages", {"thread_id": thread_id})
    async def list_events(self, since=0): return {"events": [], "cursor": since}
    # ---- write: drafts only
    async def create_proposal_draft(self, job_id, cover_letter, bid_amount, screening_answers, idempotency_key):
        r = await self._call("create_proposal_draft", {"job_id": job_id, "cover_letter": cover_letter, "bid_amount": bid_amount, "screening_answers": screening_answers})
        draft_id = r.get("draft_id") or r.get("id")
        if not draft_id:
            raise MarketplaceError("Upwork did not return a proposal draft ID", 502)
        return {**r, "draft_id": str(draft_id), "status": "draft", "connects": r.get("connects", {"total": r.get("connects_cost", 0)})}
    async def submit_proposal(self, draft_id, idempotency_key):
        return {"proposal_id": draft_id, "draft_id": draft_id, "status": "awaiting_confirmation_on_upwork",
                "note": "Live mode never submits. Open Upwork and confirm the draft yourself."}
    async def send_message(self, thread_id, text, idempotency_key):
        r = await self._call("send_message", {"thread_id": thread_id, "text": text})
        draft_id = r.get("draft_id") or r.get("id")
        if not draft_id:
            raise MarketplaceError("Upwork did not return a message draft ID", 502)
        return {**r, "id": str(draft_id), "status": "draft_awaiting_confirmation_on_upwork"}
