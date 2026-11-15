"""The conversation graph (C1): one thread per client conversation.

    load ──nothing to answer──> END
      │
    classify (question | negotiation | interview_request | scam_signal)
      │ interview_request ──> slots ──┐
      └───────────────────────────────┴─> draft ──blocked──> END
                                             │
                                          approval == interrupt()
                                   approve │        reject -> END
                                          send (message; plus a tentative hold and prep notes for interviews)
"""
from __future__ import annotations

from langgraph.graph import END, START, StateGraph
from langgraph.types import RetryPolicy

from agent.errors_util import transient
from agent.nodes import liaison as L
from agent.runtime import Ctx, halted
from agent.settings import get_settings
from agent.state import ConversationState


def build_conversation_graph(checkpointer=None, store=None):
    b = get_settings().cfg["budgets"]
    opts = dict(retry_policy=RetryPolicy(max_attempts=2, initial_interval=0.5, retry_on=transient), timeout=b["node_timeout_s"])
    g = StateGraph(ConversationState, context_schema=Ctx)
    for name, fn in (("load", L.load), ("classify", L.classify), ("slots", L.slots), ("draft", L.draft)):
        g.add_node(name, fn, **opts)
    g.add_node("approval", L.approve_reply)
    g.add_node("send", L.send, retry_policy=RetryPolicy(max_attempts=2, initial_interval=0.5, retry_on=transient))
    g.add_edge(START, "load")
    g.add_conditional_edges("load", lambda s: END if halted(s) or s.get("status") == "idle" else "classify", ["classify", END])
    g.add_conditional_edges("classify", lambda s: END if halted(s) else "slots" if s["intent"]["intent"] == "interview_request" else "draft", ["slots", "draft", END])
    g.add_conditional_edges("slots", lambda s: END if halted(s) else "draft", ["draft", END])
    g.add_conditional_edges("draft", lambda s: END if halted(s) or s.get("status") == "blocked" else "approval", ["approval", END])
    g.add_conditional_edges("approval", lambda s: "send" if not halted(s) and s.get("status") == "approved" else END, ["send", END])
    g.add_edge("send", END)
    return g.compile(checkpointer=checkpointer, store=store)


def conversation_thread_id(user_id: str, thread_id: str) -> str:
    return f"conv:{user_id}:{thread_id}"
