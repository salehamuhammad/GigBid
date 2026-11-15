"""Per-run context handed to every node (LangGraph `context_schema`) and the node wrapper that
gives all nodes the same behaviour: budgets, retries, dead-lettering, usage accounting, events."""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from langgraph.errors import GraphBubbleUp
from langgraph.runtime import Runtime

from agent.llm import LLM, get_llm
from agent.mcp_client import ToolBox, ToolNotAllowed, ToolUnavailable
from agent.settings import get_settings
from agent.state import HALTED


@dataclass
class Ctx:
    user_id: str
    owner: str                       # portfolio owner (persona id or the user's own corpus)
    trace_id: str = ""
    run_id: str = ""
    tools: ToolBox | None = None
    llm: LLM | None = None
    defences: bool = True            # injection defence on/off (measured in evals/runners/injection_eval.py)
    verify: bool = True              # claim verification on/off (ablation)
    flags: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        self.tools = self.tools or ToolBox(self.user_id, self.owner, self.trace_id)
        self.llm = self.llm or get_llm()


class Node:
    """What a node body receives: state, context, the store, and collectors for trace + usage."""
    def __init__(self, name: str, state: dict, runtime: Runtime[Ctx]):
        self.name, self.state, self.rt, self.ctx = name, state, runtime, runtime.context
        self.trace: list[dict] = []
        self.usage: list[dict] = []
        self.store = runtime.store

    async def tool(self, agent: str, tool: str, args: dict | None = None) -> dict:
        return await self.ctx.tools.call(agent, tool, args, log=self.trace)

    async def llm(self, node: str, prompt: str, variables: dict, schema, fallback: Callable):
        obj, usage = await self.ctx.llm.structured(node, prompt, variables, schema, fallback)
        self.usage.append(usage)
        return obj

    def emit(self, **data) -> None:
        """Custom stream event -> SSE -> Agent run viewer."""
        try: self.rt.stream_writer({"node": self.name, **data})
        except Exception: pass


def node(name: str, counts: bool = True):
    """Wrap a node body `async def body(n: Node) -> dict`.

    * step / token budget (C4): once exceeded the thread moves to `needs_attention` and the node does not run;
    * bounded retries with backoff for unexpected errors, then dead-letter (C7);
    * ToolUnavailable is NOT swallowed: it aborts the run, the checkpoint stays at the last good
      super-step, the worker parks the job as `queued` and resumes it when the server is back;
    * usage, trace, steps and tokens are appended to the execution trace.
    """
    def deco(body):
        async def wrapped(state: dict, runtime: Runtime[Ctx]) -> dict:
            b = get_settings().cfg["budgets"]
            if state.get("status") in HALTED:
                return {}
            if counts and (state.get("steps", 0) >= b["max_graph_steps"] or state.get("tokens", 0) >= b["max_tokens_per_thread"]):
                why = f"budget exceeded before '{name}': steps={state.get('steps', 0)}/{b['max_graph_steps']}, tokens={state.get('tokens', 0)}/{b['max_tokens_per_thread']}"
                return {"status": "needs_attention", "errors": [why]}
            n, t0, last = Node(name, state, runtime), time.perf_counter(), ""
            n.emit(event="node_start")
            for attempt in range(b["node_max_attempts"]):
                try:
                    out = await body(n) or {}
                    break
                except (GraphBubbleUp, ToolUnavailable, asyncio.CancelledError):
                    raise
                except ToolNotAllowed as e:
                    out, last = None, f"{name}: {e}"; break
                except Exception as e:  # noqa: BLE001
                    out, last = None, f"{name}: {type(e).__name__}: {str(e)[:200]}"
                    await asyncio.sleep(min(0.2 * 2 ** attempt, 2.0))
            ms = int((time.perf_counter() - t0) * 1000)
            if out is None:
                n.emit(event="node_error", error=last)
                return {"status": "dead_letter", "errors": [last], "trace": n.trace, "usage": n.usage, "steps": 1}
            tokens = sum(u.get("input_tokens", 0) + u.get("output_tokens", 0) for u in n.usage)
            if not n.usage:
                n.usage.append({"node": name, "model": "none", "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0, "latency_ms": ms})
            n.usage[-1]["node_ms"] = ms
            n.emit(event="node_end", ms=ms, tokens=tokens, cost_usd=round(sum(u.get("cost_usd", 0) for u in n.usage), 6), summary=out.pop("_summary", None))
            return {**out, "trace": n.trace + list(out.get("trace", [])), "usage": n.usage, "steps": 1 if counts else 0, "tokens": tokens}
        wrapped.__name__, wrapped.__doc__, wrapped.body = name, body.__doc__, body
        return wrapped
    return deco


def halted(state: dict) -> bool:
    return state.get("status") in HALTED
