"""Tracing (E3). One trace id flows UI -> API -> graph -> MCP servers -> audit log:

  * the web client sends `X-Trace-Id`; the API middleware echoes it and stores it on the run;
  * the graph run carries it in `Ctx.trace_id` and in LangGraph run metadata;
  * the MCP client sends it as an `X-Trace-Id` header; the Marketplace server forwards it to the
    marketplace and writes it to the audit log.

Local traces (run events with tokens, cost and latency per node) are always stored in the app
database and shown in the Agent run viewer. With LANGSMITH_TRACING=true the same run is also
sent to LangSmith, with emails, phone numbers and payment details masked before upload.
"""
from __future__ import annotations

import os
import uuid

from agent.guardrails import rules


def new_trace_id() -> str:
    return "tr-" + uuid.uuid4().hex[:20]


def langsmith_enabled() -> bool:
    return os.getenv("LANGSMITH_TRACING", "").lower() == "true" and bool(os.getenv("LANGSMITH_API_KEY"))


def run_config(thread_id: str, trace_id: str, user_id: str, kind: str, ref: str, langsmith_run_id: str | None = None) -> dict:
    cfg: dict = {"configurable": {"thread_id": thread_id}, "metadata": {"trace_id": trace_id, "user_id": user_id, "kind": kind, "ref": ref},
                 "tags": [kind, f"trace:{trace_id}"], "run_name": f"gigbid:{kind}:{ref}", "recursion_limit": 60}
    if langsmith_enabled():
        from langchain_core.tracers.langchain import LangChainTracer
        from langsmith import Client
        from langsmith.anonymizer import create_anonymizer
        anonymizer = create_anonymizer([{"pattern": p, "replace": f"[{name}]"} for name, p in rules().get("pii_patterns", {}).items()])
        cfg["callbacks"] = [LangChainTracer(client=Client(anonymizer=anonymizer), project_name=os.getenv("LANGSMITH_PROJECT", "gigbid"))]
        if langsmith_run_id: cfg["run_id"] = uuid.UUID(langsmith_run_id)
    return cfg


def public_trace_url(langsmith_run_id: str) -> str | None:
    """Share one run publicly (for the README's trace links). Returns None when LangSmith is off."""
    if not langsmith_enabled(): return None
    try:
        from langsmith import Client
        return Client().share_run(langsmith_run_id)
    except Exception:
        return None
