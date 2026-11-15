"""R1: the ONE marketplace interface. Everything that touches a marketplace -- GigSim or live
Upwork -- goes through this port. The Marketplace MCP server is its only caller, so the graph
cannot tell which marketplace it is talking to; switching is one config value
(`marketplace.mode` / MARKETPLACE_MODE)."""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


class MarketplaceUnavailable(Exception):
    """The marketplace could not be reached after bounded retries (degraded mode)."""


class MarketplaceError(Exception):
    """The marketplace answered with a business error (4xx): do not retry."""
    def __init__(self, message: str, status: int = 400):
        super().__init__(message); self.status = status


@runtime_checkable
class MarketplacePort(Protocol):
    name: str
    # ---- read
    async def search_jobs(self, query: str, category: str | None = None, limit: int = 20, offset: int = 0) -> dict[str, Any]: ...
    async def get_job(self, job_id: str) -> dict[str, Any]: ...
    async def get_client_history(self, client_id: str) -> dict[str, Any]: ...
    async def get_connects_balance(self) -> dict[str, Any]: ...
    async def get_market_stats(self, category: str) -> dict[str, Any]: ...
    async def get_policy(self) -> dict[str, Any]: ...
    async def list_threads(self) -> dict[str, Any]: ...
    async def list_messages(self, thread_id: str) -> dict[str, Any]: ...
    async def list_events(self, since: int = 0) -> dict[str, Any]: ...
    # ---- write (each call carries an idempotency key)
    async def create_proposal_draft(self, job_id: str, cover_letter: str, bid_amount: float, screening_answers: list[str], idempotency_key: str) -> dict[str, Any]: ...
    async def submit_proposal(self, draft_id: str, idempotency_key: str) -> dict[str, Any]: ...
    async def send_message(self, thread_id: str, text: str, idempotency_key: str) -> dict[str, Any]: ...


def get_port(account: str, trace_id: str = "", mode: str | None = None) -> MarketplacePort:
    from agent.settings import get_settings
    mode = mode or get_settings().marketplace_mode
    if mode == "upwork":
        from mcp_servers.marketplace.adapters.upwork_live import UpworkLiveAdapter
        return UpworkLiveAdapter(account, trace_id)
    from mcp_servers.marketplace.adapters.gigsim import GigSimAdapter
    return GigSimAdapter(account, trace_id)
