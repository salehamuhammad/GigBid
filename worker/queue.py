"""Task queue. With REDIS_URL set, tasks go to the arq worker (worker/main.py) -- the web process
never runs an agent. Without Redis (bare local run, tests) the same task functions run as
background asyncio tasks in the API process, so the product behaves identically."""
from __future__ import annotations

import asyncio
import logging

from agent.settings import get_settings

log = logging.getLogger("gigbid.queue")
_pool = None
_tasks: set[asyncio.Task] = set()
_running: set[str] = set()


async def _arq():
    global _pool
    if _pool is None:
        from arq import create_pool
        from arq.connections import RedisSettings
        _pool = await create_pool(RedisSettings.from_dsn(get_settings().redis_url))
    return _pool


async def enqueue(name: str, *args, key: str | None = None) -> None:
    """`key` de-duplicates: the same key is never queued twice while it is pending or running."""
    if get_settings().redis_url:
        await (await _arq()).enqueue_job(name, *args, _job_id=key)
        return
    from worker import tasks
    key = key or f"{name}:{args}"
    if key in _running: return
    _running.add(key)

    async def run():
        try:
            await getattr(tasks, name)(*args)
        except Exception:  # noqa: BLE001
            log.exception("task %s failed", name)
        finally:
            _running.discard(key)

    t = asyncio.create_task(run()); _tasks.add(t); t.add_done_callback(_tasks.discard)


async def drain(timeout: float = 60) -> None:
    """Wait for in-process tasks (tests, demo script)."""
    while _tasks:
        await asyncio.wait(list(_tasks), timeout=timeout)
