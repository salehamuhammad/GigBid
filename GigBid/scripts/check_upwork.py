"""List the tools the official Upwork MCP server exposes to your connected account, and check
`marketplace.upwork.tool_map` against them.   python -m scripts.check_upwork --user <user_id>"""
import argparse
import asyncio

from agent.settings import get_settings
from mcp_servers.marketplace.adapters.upwork_live import UpworkLiveAdapter


async def main(user: str):
    a = UpworkLiveAdapter(user)
    async with a._client().session("upwork") as s:
        names = sorted(t.name for t in (await s.list_tools()).tools)
    print("Upwork MCP tools:", names)
    for method, tool in get_settings().cfg["marketplace"]["upwork"]["tool_map"].items():
        print(f"  {'ok     ' if tool in names else 'MISSING'} {method:24s} -> {tool}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--user", required=True)
    asyncio.run(main(ap.parse_args().user))
