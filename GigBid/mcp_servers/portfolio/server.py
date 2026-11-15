"""Portfolio MCP server (A1), read-only. Usable on its own from Claude Desktop, Cursor or the
MCP Inspector:

    gigbid-portfolio-mcp --owner ai_engineer                 # stdio
    python -m mcp_servers.portfolio.server --transport http --port 8101

See mcp_servers/portfolio/README.md for install instructions and pointing it at your own files.
"""
from __future__ import annotations

import argparse
import os

from mcp.server.fastmcp import FastMCP

from mcp_servers.common import Identity, serve
from mcp_servers.portfolio import prompts, resources, tools


def build_server(default: Identity | None = None, host: str = "0.0.0.0", port: int = 8101) -> FastMCP:
    mcp = FastMCP("gigbid-portfolio", instructions="Read-only access to a freelancer's portfolio: case studies, repositories, reviews, CV and past proposals with outcomes. "
                  "Use search_evidence to prove a requirement before claiming experience; item text is the only source of truth.", host=host, port=port, stateless_http=True, json_response=True)
    tools.register(mcp, default); resources.register(mcp, default); prompts.register(mcp)
    return mcp


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--owner", default=os.getenv("PORTFOLIO_OWNER", "ai_engineer"), help="persona / portfolio folder name under <data-dir>/personas/")
    ap.add_argument("--data-dir", default=None, help="directory containing personas/<owner>/ (default: the repo's data/)")
    args, _ = ap.parse_known_args()
    if args.data_dir:
        os.environ["GIGBID_DATA_DIR"] = args.data_dir
        from agent.settings import reload_settings
        reload_settings()
    serve(build_server(Identity(user="local", owner=args.owner)), 8101)


if __name__ == "__main__":
    main()
