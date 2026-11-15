"""arq worker (Redis). Run:  arq worker.main.WorkerSettings

Schedules: `tick` every 30 s checks which saved searches are due. Each search has its own
interval, floored by `marketplace.scout_interval_minutes` for the active marketplace
(5 min on GigSim, 180 min in live mode -- justified in docs/RUNBOOK.md).
"""
from __future__ import annotations

import logging

from arq import cron
from arq.connections import RedisSettings

from agent.guardrails import install_log_masking
from agent.settings import get_settings
from worker import tasks
from worker.engine import ENGINE


async def startup(ctx):
    logging.basicConfig(level=logging.INFO); install_log_masking()
    await ENGINE.start(); await tasks.recover()


async def shutdown(ctx):
    await ENGINE.stop()


def _wrap(name):
    async def fn(ctx, *args):
        return await getattr(tasks, name)(*args)
    fn.__name__ = fn.__qualname__ = name
    return fn


class WorkerSettings:
    functions = [_wrap(n) for n in ("run_bid", "resume_bid", "run_conversation", "resume_conversation", "scout_user", "poll_events", "retry_queued", "tick")]
    cron_jobs = [cron(_wrap("tick"), second={0, 30}, unique=True)]
    on_startup, on_shutdown = startup, shutdown
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url or "redis://localhost:6379/0")
    max_jobs, job_timeout, keep_result, max_tries = 4, 600, 0, 3
