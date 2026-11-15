"""GigSim adapter for the marketplace port: REST over httpx with timeouts, bounded retries with
exponential backoff, and Retry-After handling for 429s (C7, R9)."""
from __future__ import annotations

import asyncio
import random
from typing import Any

import httpx

from agent.marketplace_port import MarketplaceError, MarketplaceUnavailable
from agent.settings import get_settings

_transport: httpx.AsyncBaseTransport | None = None      # tests mount the GigSim ASGI app here


def set_transport(t: httpx.AsyncBaseTransport | None) -> None:
    global _transport
    _transport = t


class GigSimAdapter:
    name = "gigsim"

    def __init__(self, account: str, trace_id: str = ""):
        s = get_settings(); m = s.cfg["marketplace"]
        self.base, self.timeout, self.retries, self.backoff = s.gigsim_url, m["timeout_s"], m["max_retries"], m["backoff_base_s"]
        self.headers = {"Authorization": f"Bearer {s.gigsim_token}", "X-Account": account, "X-Trace-Id": trace_id}

    async def _req(self, method: str, path: str, *, params=None, json=None, key: str | None = None) -> dict[str, Any]:
        headers = dict(self.headers) | ({"Idempotency-Key": key} if key else {})
        last = "unknown error"
        for attempt in range(self.retries + 1):
            try:
                async with httpx.AsyncClient(base_url=self.base, timeout=self.timeout, transport=_transport) as c:
                    r = await c.request(method, path, params=params, json=json, headers=headers)
                if r.status_code == 429:
                    last = "rate limited"; wait = min(float(r.headers.get("Retry-After", 1)), 8.0)
                elif r.status_code >= 500:
                    last = f"HTTP {r.status_code}"; wait = self.backoff * 2 ** attempt + random.uniform(0, 0.1)
                elif r.status_code >= 400:
                    body = r.json() if "json" in r.headers.get("content-type", "") else {"error": r.text}
                    raise MarketplaceError(str(body.get("error") or body.get("detail") or body), r.status_code)
                else:
                    return r.json()
            except (httpx.TransportError, httpx.TimeoutException) as e:
                last = f"{type(e).__name__}"; wait = self.backoff * 2 ** attempt
            if attempt < self.retries: await asyncio.sleep(wait)
        raise MarketplaceUnavailable(f"GigSim unavailable after {self.retries + 1} attempts ({last})")

    async def search_jobs(self, query, category=None, limit=20, offset=0):
        return await self._req("GET", "/jobs/search", params={"q": query, "limit": limit, "offset": offset} | ({"category": category} if category else {}))
    async def get_job(self, job_id): return await self._req("GET", f"/jobs/{job_id}")
    async def get_client_history(self, client_id): return await self._req("GET", f"/clients/{client_id}/history")
    async def get_connects_balance(self): return await self._req("GET", "/connects")
    async def get_market_stats(self, category): return await self._req("GET", "/market/stats", params={"category": category})
    async def get_policy(self): return await self._req("GET", "/policy")
    async def list_threads(self): return await self._req("GET", "/threads")
    async def list_messages(self, thread_id): return await self._req("GET", f"/threads/{thread_id}/messages")
    async def list_events(self, since=0): return await self._req("GET", "/events", params={"since": since})
    async def create_proposal_draft(self, job_id, cover_letter, bid_amount, screening_answers, idempotency_key):
        return await self._req("POST", "/proposals/drafts", json={"job_id": job_id, "cover_letter": cover_letter, "bid_amount": bid_amount, "screening_answers": screening_answers}, key=idempotency_key)
    async def submit_proposal(self, draft_id, idempotency_key):
        return await self._req("POST", f"/proposals/{draft_id}/submit", key=idempotency_key)
    async def send_message(self, thread_id, text, idempotency_key):
        return await self._req("POST", "/messages", json={"thread_id": thread_id, "text": text}, key=idempotency_key)
