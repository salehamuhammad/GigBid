"""Server-Sent Events for agent runs (D: stream progress, never a spinner).

The worker (possibly another process) appends run events to the database; this endpoint tails
them. Because events are persisted, refreshing the page replays the run from the start and a
pending approval is never lost."""
from __future__ import annotations

import asyncio
import json
import time

from sqlalchemy import select

from apps.api.db import Run, RunEvent, session


async def run_event_stream(run_id: str, user_id: str, after: int = 0):
    last, idle_since = after, time.time()
    yield "retry: 2000\n\n"
    while True:
        with session() as s:
            rows = list(s.scalars(select(RunEvent).where(RunEvent.run_id == run_id, RunEvent.user_id == user_id, RunEvent.id > last).order_by(RunEvent.id).limit(200)))
            run = s.get(Run, run_id)
            status = run.status if run and run.user_id == user_id else "missing"
        for r in rows:
            last = r.id; idle_since = time.time()
            yield f"id: {r.id}\nevent: {r.type}\ndata: {json.dumps({'id': r.id, 'ts': r.ts, 'node': r.node, 'type': r.type, 'payload': r.payload})}\n\n"
        if status != "running" and not rows:
            yield f"event: done\ndata: {json.dumps({'status': status})}\n\n"; return
        if time.time() - idle_since > 15:
            idle_since = time.time(); yield ": keep-alive\n\n"
        await asyncio.sleep(0.4)
