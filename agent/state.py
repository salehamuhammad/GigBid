"""Typed graph state (C2). Three things are kept apart on purpose:

  STATE            what this job / conversation needs right now (job, analyses, evidence,
                   decision, price, draft, critiques, approval, outcome).
  EXECUTION TRACE  `trace` (every tool name, arguments, result summary), `usage` (tokens, cost,
                   latency per node) and `errors`. Append-only, for audit and debugging; no node
                   reads it to make a decision.
  LONG-TERM MEMORY is NOT in the state. It lives in the LangGraph store and is written only by
                   agent/memory/promotion_rules.py. A read-only snapshot is copied into
                   `memory` at intake so a run is reproducible from its checkpoint.

Reducers are declared wherever parallel branches (analyst / risk / matcher) write the same key.
"""
from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict


def merge(a: dict | None, b: dict | None) -> dict:
    return {**(a or {}), **(b or {})}


def add(a: int | None, b: int | None) -> int:
    """Counter reducer. Writing None resets it (a new turn of a conversation starts a new budget)."""
    return 0 if b is None else (a or 0) + b


class BidState(TypedDict, total=False):
    # ---- state
    job: dict[str, Any]                         # sanitised job post (untrusted text already scanned)
    user: dict[str, Any]                        # profile snapshot: rates, budget, autonomy, strategy
    memory: dict[str, Any]                      # read-only snapshot of promoted style + outcome memory
    analyses: Annotated[dict[str, Any], merge]  # job_spec | risk | fit  (written in parallel)
    evidence: Annotated[dict[str, Any], merge]  # evidence id -> full item (text, skills, ...)
    decision: dict[str, Any]
    price: dict[str, Any]
    policy: dict[str, Any]
    draft: dict[str, Any]
    verification: dict[str, Any]
    critiques: Annotated[list[dict], operator.add]
    revisions: int
    compliance: dict[str, Any]
    preview: dict[str, Any]
    approval: dict[str, Any]
    approvals: Annotated[list[dict], operator.add]
    outcome: dict[str, Any]
    status: str
    # ---- execution trace
    trace: Annotated[list[dict], operator.add]
    usage: Annotated[list[dict], operator.add]
    errors: Annotated[list[str], operator.add]
    steps: Annotated[int, add]
    tokens: Annotated[int, add]


class ConversationState(TypedDict, total=False):
    thread_id: str
    user: dict[str, Any]
    job: dict[str, Any]
    messages: list[dict]
    last_client_message: dict[str, Any]
    intent: dict[str, Any]
    slots: list[dict]
    reply: dict[str, Any]
    compliance: dict[str, Any]
    preview: dict[str, Any]
    approval: dict[str, Any]
    outcome: dict[str, Any]
    status: str
    trace: Annotated[list[dict], operator.add]
    usage: Annotated[list[dict], operator.add]
    errors: Annotated[list[str], operator.add]
    steps: Annotated[int, add]
    tokens: Annotated[int, add]


HALTED = ("needs_attention", "dead_letter")
