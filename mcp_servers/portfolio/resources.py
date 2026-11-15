"""Resource templates so a host (Claude Desktop, Cursor) can load full items by URI."""
from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from mcp_servers.common import Identity
from mcp_servers.portfolio.tools import get_item
from rag.retriever import owner_index


def register(mcp: FastMCP, default: Identity | None) -> None:
    owner = lambda: (default or Identity()).owner

    def render(item_id: str) -> str:
        it = get_item(owner(), item_id)
        head = f"# {it.title}\n\n- id: {it.id}\n- type: {it.type}\n- date: {it.date}\n- industry: {it.client_industry}\n- skills: {', '.join(it.skills)}\n- outcome: {it.outcome}\n\n"
        return head + it.text + (f"\n\n## Code\n```\n{it.code}\n```" if it.code else "")

    @mcp.resource("portfolio://case/{id}", name="case_study", description="One case study, repo or review as Markdown", mime_type="text/markdown")
    def case(id: str) -> str: return render(id)

    @mcp.resource("portfolio://proposal/{id}", name="past_proposal", description="One past proposal with its outcome (won / replied / ignored)", mime_type="text/markdown")
    def proposal(id: str) -> str: return render(id)

    @mcp.resource("portfolio://index", name="portfolio_index", description="List of every portfolio item id, type and title", mime_type="text/markdown")
    def index() -> str:
        return "\n".join(f"- `{d.id}` ({d.type}) {d.title}" for d in owner_index(owner()).docs.values())
