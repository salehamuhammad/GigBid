"""MCP client side (A6). Agents reach every capability through `ToolBox.call(agent, "server.tool", args)`:

  * per-agent allowlists from agent/config.yaml (`tools.allow`) -- a tool that is not listed for
    the calling agent is refused before any network call;
  * timeouts, bounded retries with exponential backoff;
  * a clear degraded mode: when a server stays unreachable `ToolUnavailable` is raised, the
    worker parks the job as `queued` and the UI shows a "marketplace unavailable" banner;
  * every call is appended to the execution trace (tool, masked arguments, result summary, ms).

Transports: `http` uses MultiServerMCPClient over Streamable HTTP with a per-user bearer token
and the trace id in a header; `inprocess` connects to the same server objects through the MCP
SDK's in-memory transport (single-process dev, tests, CI).
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import time
from contextlib import asynccontextmanager
from typing import Any

from agent.guardrails import mask_obj
from agent.settings import get_settings
from mcp_servers.common import Identity, issue_token

SERVERS = ("portfolio", "marketplace", "workspace")


class ToolUnavailable(Exception):
    def __init__(self, server: str, detail: str = ""):
        super().__init__(f"{server} MCP server unavailable: {detail}"); self.server = server


class ToolError(Exception):
    pass


class ToolNotAllowed(PermissionError):
    pass


def _build(server: str, ident: Identity):
    if server == "portfolio":
        from mcp_servers.portfolio.server import build_server
    elif server == "marketplace":
        from mcp_servers.marketplace.server import build_server
    else:
        from mcp_servers.workspace.server import build_server
    return build_server(ident)


_cache: dict[tuple, tuple[float, dict]] = {}


class ToolBox:
    def __init__(self, user: str, owner: str, trace_id: str = ""):
        s = get_settings()
        self.ident = Identity(user, owner, trace_id)
        self.cfg = s.cfg["tools"]
        self.transport = s.mcp_transport
        self._local: dict[str, Any] = {}
        self._mc = None

    def allowed(self, agent: str) -> list[str]:
        return self.cfg["allow"].get(agent, [])

    def _check(self, agent: str, tool: str) -> None:
        allow = self.allowed(agent)
        if "*" not in allow and tool not in allow:
            raise ToolNotAllowed(f"agent '{agent}' may not call '{tool}' (allowed: {allow})")

    def _client(self):
        if self._mc is None:
            from langchain_mcp_adapters.client import MultiServerMCPClient
            headers = {"Authorization": f"Bearer {issue_token(self.ident.user, self.ident.owner)}", "X-Trace-Id": self.ident.trace_id}
            urls = {n: os.getenv(f"MCP_{n.upper()}_URL", f"http://localhost:{8101 + i}/mcp") for i, n in enumerate(SERVERS)}
            self._mc = MultiServerMCPClient({n: {"transport": "streamable_http", "url": u, "headers": headers} for n, u in urls.items()})
        return self._mc

    @asynccontextmanager
    async def session(self, server: str):
        if self.transport == "http":
            async with self._client().session(server) as s:
                yield s
        else:
            from mcp.shared.memory import create_connected_server_and_client_session
            if server not in self._local: self._local[server] = _build(server, self.ident)
            async with create_connected_server_and_client_session(self._local[server]._mcp_server) as s:
                yield s

    async def call(self, agent: str, tool: str, args: dict | None = None, log: list | None = None) -> dict:
        self._check(agent, tool)
        server, name = tool.split(".", 1)
        args = {k: v for k, v in (args or {}).items() if v is not None}
        t0, last, limited = time.perf_counter(), "", 0
        ckey = (self.ident.user if server != "marketplace" or name != "get_policy" else "", self.ident.owner, tool, json.dumps(args, sort_keys=True, default=str))
        if tool in self.cfg.get("cacheable", []) and ckey in _cache and time.time() - _cache[ckey][0] < self.cfg.get("cache_ttl_s", 0):
            return _cache[ckey][1]
        for attempt in range(self.cfg["max_retries"] + 1):
            try:
                async with asyncio.timeout(self.cfg["timeout_s"]):
                    async with self.session(server) as s:
                        res = await s.call_tool(name, args)
                text = " ".join(getattr(c, "text", "") for c in res.content)
                if res.isError:
                    if "MARKETPLACE_UNAVAILABLE" in text: raise ToolUnavailable(server, text[:200])
                    if "RATE_LIMITED" in text:
                        # our own polite limiter: wait once for a slot, otherwise park the work (it resumes from its checkpoint)
                        m = re.search(r"retry after (\d+)", text); wait = float(m.group(1)) if m else 5.0
                        limited += 1
                        if limited > 1 or wait > 20: raise ToolUnavailable(server, f"rate limited; retry in {wait:.0f}s")
                        last = text; await asyncio.sleep(wait + 0.5); continue
                    raise ToolError(text[:400])
                out = res.structuredContent if res.structuredContent is not None else json.loads(text or "{}")
                if isinstance(out, dict) and set(out) == {"result"}: out = out["result"]
                self._log(log, agent, tool, args, out, t0, True)
                if tool in self.cfg.get("cacheable", []): _cache[ckey] = (time.time(), out)
                return out
            except (ToolError, ToolNotAllowed):
                self._log(log, agent, tool, args, last or "tool error", t0, False); raise
            except ToolUnavailable:
                self._log(log, agent, tool, args, "unavailable", t0, False); raise
            except BaseException as e:  # transport failure, timeout, cancelled task group
                if isinstance(e, (KeyboardInterrupt, asyncio.CancelledError)) and not isinstance(e, TimeoutError): raise
                last = f"{type(e).__name__}: {str(e)[:120]}"
                if attempt < self.cfg["max_retries"]: await asyncio.sleep(self.cfg["backoff_base_s"] * 2 ** attempt)
        self._log(log, agent, tool, args, last, t0, False)
        raise ToolUnavailable(server, last)

    def _log(self, log, agent, tool, args, result, t0, ok):
        if log is None: return
        brief = result if isinstance(result, str) else {k: (v if isinstance(v, (int, float, bool)) or v is None or len(str(v)) < 160 else f"<{type(v).__name__}:{len(v)}>") for k, v in result.items()} if isinstance(result, dict) else str(result)[:160]
        log.append({"agent": agent, "tool": tool, "arguments": mask_obj(args), "result": mask_obj(brief), "ok": ok, "ms": int((time.perf_counter() - t0) * 1000),
                    "trace_id": self.ident.trace_id, "at": time.time()})

    async def health(self) -> dict[str, bool]:
        out = {}
        for server in SERVERS:
            try:
                async with asyncio.timeout(5):
                    async with self.session(server) as s:
                        await s.list_tools()
                out[server] = True
            except BaseException as e:
                if isinstance(e, asyncio.CancelledError) and not isinstance(e, TimeoutError): raise
                out[server] = False
        return out

    async def list_tools(self, servers=SERVERS) -> list[dict]:
        out = []
        for server in servers:
            async with self.session(server) as s:
                for t in (await s.list_tools()).tools:
                    out.append({"server": server, "name": t.name, "description": t.description, "inputSchema": t.inputSchema, "outputSchema": t.outputSchema,
                                "annotations": t.annotations.model_dump(exclude_none=True) if t.annotations else {}})
        return out

    async def langchain_tools(self, agent: str, rename: dict[str, str] | None = None, describe: dict[str, str] | None = None) -> list:
        """LangChain tools for `agent`, filtered by its allowlist (used by the single-agent demo and the R&D baselines)."""
        from langchain_core.tools import StructuredTool
        allow, tools = self.allowed(agent), []
        for t in await self.list_tools():
            full = f"{t['server']}.{t['name']}"
            if "*" not in allow and full not in allow: continue
            async def _run(_full=full, **kwargs):
                try: return json.dumps(await self.call(agent, _full, kwargs), default=str)[:6000]
                except Exception as e: return f"ERROR: {e}"
            tools.append(StructuredTool.from_function(coroutine=_run, name=(rename or {}).get(full, t["name"]), description=(describe or {}).get(full, t["description"]), args_schema=t["inputSchema"]))
        return tools
