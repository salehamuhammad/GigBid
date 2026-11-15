"""The bid graph (C1): one thread per job. Hand-written StateGraph.

    intake --Send--> analyst ┐
           --Send--> risk    ├─> decide ──skip/watch──> END
           --Send--> matcher ┘      │bid
                                  pricing ──not worth the Connects──> END
                                    │
                                  writer <──────────────┐ (Critic sends back, at most twice)
                                    │                   │
                                  verifier ──> critic ──┘
                                                 │
                                             compliance ──blocked──> END (reason shown in UI)
                                                 │
                                             approval  == interrupt(): human approves / edits / rejects / regenerates
                              edit │   approve │   reject │   regenerate -> writer
                          apply_edit ->compliance    submit      END
                                                 │
                                                END

Any node can move the thread to `needs_attention` (step/token budget) or `dead_letter`
(retries exhausted); both end the run in a state the UI shows.
"""
from __future__ import annotations

from langgraph.graph import END, START, StateGraph
from langgraph.types import RetryPolicy, Send

from agent.errors_util import transient
from agent.nodes.analyst import analyst
from agent.nodes.compliance import compliance
from agent.nodes.critic import critic
from agent.nodes.decide import decide
from agent.nodes.gateway import apply_edit, approval, submit
from agent.nodes.matcher import matcher
from agent.nodes.pricing import pricing
from agent.nodes.risk import risk
from agent.nodes.scout import intake
from agent.nodes.verifier import verifier
from agent.nodes.writer import writer
from agent.runtime import Ctx, halted
from agent.settings import get_settings
from agent.state import BidState

PARALLEL = ("analyst", "risk", "matcher")


def fan_out(state: BidState):
    """Job Analyst, Risk Assessor and Fit Matcher run in parallel (R3) via Send."""
    if halted(state): return END
    return [Send(name, state) for name in PARALLEL]


def after_decide(state: BidState) -> str:
    if halted(state): return END
    return "pricing" if state.get("decision", {}).get("action") == "bid" else END


def after_pricing(state: BidState) -> str:
    if halted(state): return END
    return "writer" if state.get("price", {}).get("worth_connects") else END


def after_critic(state: BidState) -> str:
    if halted(state): return END
    last = (state.get("critiques") or [{}])[-1]
    return "writer" if last.get("sent_back") else "compliance"


def after_compliance(state: BidState) -> str:
    if halted(state) or state.get("status") == "blocked": return END
    return "approval"


def after_approval(state: BidState) -> str:
    if halted(state): return END
    return {"approve": "submit", "edit": "apply_edit", "regenerate": "writer"}.get((state.get("approval") or {}).get("action"), END)


def go(nxt: str):
    return lambda state: END if halted(state) else nxt


def build_bid_graph(checkpointer=None, store=None):
    b = get_settings().cfg["budgets"]
    opts = dict(retry_policy=RetryPolicy(max_attempts=2, initial_interval=0.5, retry_on=transient), timeout=b["node_timeout_s"])
    g = StateGraph(BidState, context_schema=Ctx)
    for name, fn in (("intake", intake), ("analyst", analyst), ("risk", risk), ("matcher", matcher), ("decide", decide), ("pricing", pricing), ("writer", writer),
                     ("verifier", verifier), ("critic", critic), ("compliance", compliance), ("apply_edit", apply_edit)):
        g.add_node(name, fn, **opts)
    g.add_node("approval", approval)      # no timeout: it waits for a human
    g.add_node("submit", submit, retry_policy=RetryPolicy(max_attempts=2, initial_interval=0.5, retry_on=transient))
    g.add_edge(START, "intake")
    g.add_conditional_edges("intake", fan_out, [*PARALLEL, END])
    g.add_edge(list(PARALLEL), "decide")
    g.add_conditional_edges("decide", after_decide, ["pricing", END])
    g.add_conditional_edges("pricing", after_pricing, ["writer", END])
    g.add_conditional_edges("writer", go("verifier"), ["verifier", END])
    g.add_conditional_edges("verifier", go("critic"), ["critic", END])
    g.add_conditional_edges("critic", after_critic, ["writer", "compliance", END])
    g.add_conditional_edges("compliance", after_compliance, ["approval", END])
    g.add_conditional_edges("approval", after_approval, ["submit", "apply_edit", "writer", END])
    g.add_conditional_edges("apply_edit", go("compliance"), ["compliance", END])
    g.add_edge("submit", END)
    return g.compile(checkpointer=checkpointer, store=store)


def bid_thread_id(user_id: str, job_id: str) -> str:
    return f"bid:{user_id}:{job_id}"
