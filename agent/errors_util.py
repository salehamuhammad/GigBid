"""Which exceptions LangGraph's RetryPolicy should retry at node level."""
from __future__ import annotations

from langgraph.errors import GraphBubbleUp

from agent.mcp_client import ToolNotAllowed, ToolUnavailable


def transient(exc: Exception) -> bool:
    """Retry timeouts and unexpected errors; never retry an interrupt, an outage that already
    exhausted its own retries, or a permission error."""
    return not isinstance(exc, (GraphBubbleUp, ToolUnavailable, ToolNotAllowed))
