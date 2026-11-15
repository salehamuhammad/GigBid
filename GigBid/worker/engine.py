"""Process-wide graph engine: the two compiled graphs on a durable checkpointer + store."""
from __future__ import annotations

from agent.graphs.bid_graph import build_bid_graph
from agent.graphs.conversation_graph import build_conversation_graph
from agent.persistence import open_persistence


class Engine:
    def __init__(self):
        self.started, self._cm = False, None
        self.saver = self.store = self.bid = self.conv = None

    async def start(self) -> "Engine":
        if self.started: return self
        self._cm = open_persistence()
        self.saver, self.store = await self._cm.__aenter__()
        self.bid, self.conv = build_bid_graph(self.saver, self.store), build_conversation_graph(self.saver, self.store)
        self.started = True
        return self

    async def stop(self) -> None:
        if self.started:
            await self._cm.__aexit__(None, None, None)
            self.started = False


ENGINE = Engine()


async def engine() -> Engine:
    return await ENGINE.start()
