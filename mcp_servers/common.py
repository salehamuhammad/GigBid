"""Shared plumbing for the three GigBid MCP servers: identity, bearer auth, rate limiting,
append-only audit log and the write-idempotency store."""
from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path

import jwt

from agent.guardrails import mask_obj
from agent.settings import get_settings


@dataclass
class Identity:
    user: str = "local"
    owner: str = "ai_engineer"       # whose portfolio this user works with
    trace_id: str = ""


def issue_token(user: str, owner: str, ttl_s: int = 3600) -> str:
    return jwt.encode({"sub": user, "owner": owner, "exp": int(time.time()) + ttl_s}, get_settings().secret, algorithm="HS256")


def identity_from_headers(headers) -> Identity | None:
    auth = headers.get("authorization", "")
    if not auth.lower().startswith("bearer "): return None
    tok = auth.split(" ", 1)[1]
    static = os.getenv("MCP_STATIC_TOKEN")
    if static and tok == static:
        return Identity(headers.get("x-user", "local"), headers.get("x-owner", "ai_engineer"), headers.get("x-trace-id", ""))
    try:
        c = jwt.decode(tok, get_settings().secret, algorithms=["HS256"])
        return Identity(str(c["sub"]), c.get("owner", "ai_engineer"), headers.get("x-trace-id", ""))
    except Exception:
        return None


def identity(ctx, default: Identity | None) -> Identity:
    """Identity of the caller: from the HTTP bearer token, else the identity the server was built with
    (stdio / in-process). There is no anonymous access over HTTP -- BearerAuth rejects it first."""
    try:
        req = ctx.request_context.request
        if req is not None:
            ident = identity_from_headers(req.headers)
            if ident: return ident
    except Exception:
        pass
    return default or Identity()


class BearerAuth:
    """ASGI middleware: 401 unless the request carries a valid bearer token (A2)."""
    def __init__(self, app): self.app = app
    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
            if scope.get("path", "").rstrip("/") != "/health" and identity_from_headers(headers) is None:
                body = json.dumps({"error": "unauthorized", "detail": "Bearer token required"}).encode()
                await send({"type": "http.response.start", "status": 401, "headers": [(b"content-type", b"application/json"), (b"www-authenticate", b"Bearer")]})
                await send({"type": "http.response.body", "body": body}); return
        await self.app(scope, receive, send)


class RateLimiter:
    """Per-user sliding window. Waits briefly for a slot; if none frees up, reports how long to wait.
    Sized below the marketplace's own limit so we never trip it (A2, R9)."""
    def __init__(self, per_minute: int): self.n, self.calls = per_minute, defaultdict(deque)
    async def acquire(self, user: str, max_wait: float = 5.0) -> float:
        t_end = time.monotonic() + max_wait
        while True:
            q, now = self.calls[user], time.monotonic()
            while q and now - q[0] > 60: q.popleft()
            if len(q) < self.n:
                q.append(now); return 0.0
            wait = 60 - (now - q[0])
            if now + min(wait, 0.25) > t_end: return wait
            await asyncio.sleep(min(wait, 0.25))


class AuditLog:
    """Append-only JSONL: who called which tool with what, what came back, under which trace id."""
    def __init__(self, name: str):
        d = get_settings().processed / "audit"; d.mkdir(parents=True, exist_ok=True)
        self.path = d / f"{name}_audit.jsonl"
    def write(self, ident: Identity, tool: str, arguments: dict, result: dict | str, ok: bool = True) -> None:
        rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "user": ident.user, "tool": tool, "arguments": mask_obj(arguments),
               "result": mask_obj(_brief(result)), "ok": ok, "trace_id": ident.trace_id}
        with open(self.path, "a") as f: f.write(json.dumps(rec, default=str) + "\n")
    def tail(self, n: int = 50, user: str | None = None) -> list[dict]:
        if not self.path.exists(): return []
        rows = [json.loads(l) for l in self.path.read_text().splitlines()[-2000:] if l.strip()]
        return [r for r in rows if not user or r["user"] == user][-n:]


def _brief(result):
    if isinstance(result, dict):
        return {k: (v if not isinstance(v, (list, dict, str)) or len(str(v)) < 200 else f"<{type(v).__name__} len={len(v)}>") for k, v in result.items()}
    return str(result)[:300]


class IdempotencyStore:
    """key -> stored result. A retried write returns the first result and never reaches the marketplace again."""
    def __init__(self, path: Path | None = None):
        self.db = sqlite3.connect(str(path or get_settings().processed / "mcp_idempotency.sqlite"), check_same_thread=False, timeout=30)
        self.db.execute("create table if not exists idem (user text, tool text, key text, result text, at real, primary key (user, tool, key))")
        self.db.commit()
    def get(self, user: str, tool: str, key: str) -> dict | None:
        row = self.db.execute("select result from idem where user=? and tool=? and key=?", (user, tool, key)).fetchone()
        return json.loads(row[0]) if row else None
    def put(self, user: str, tool: str, key: str, result: dict) -> None:
        self.db.execute("insert or ignore into idem values (?,?,?,?,?)", (user, tool, key, json.dumps(result, default=str), time.time())); self.db.commit()


def serve(mcp, default_port: int, auth: bool = True) -> None:
    """Run a FastMCP server: stdio (default, for Claude Desktop / Cursor / Inspector) or HTTP."""
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--transport", choices=["stdio", "http"], default=os.getenv("MCP_SERVER_TRANSPORT", "stdio"))
    ap.add_argument("--host", default=os.getenv("MCP_HOST", "0.0.0.0")); ap.add_argument("--port", type=int, default=int(os.getenv("PORT", default_port)))
    args, _ = ap.parse_known_args()
    if args.transport == "stdio":
        mcp.run("stdio"); return
    import uvicorn
    from starlette.responses import JSONResponse
    from starlette.routing import Route
    app = mcp.streamable_http_app()
    app.router.routes.append(Route("/health", lambda r: JSONResponse({"status": "ok", "server": mcp.name})))
    uvicorn.run(BearerAuth(app) if auth else app, host=args.host, port=args.port, log_level="warning")
