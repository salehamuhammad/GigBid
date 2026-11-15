"""Durable graph persistence (C6): a checkpointer and a store.

Postgres when DATABASE_URL points at Postgres (docker compose, deployment); SQLite files under
data/processed/ otherwise, so the crash-and-resume behaviour is identical on a laptop.
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from agent.settings import get_settings


@asynccontextmanager
async def open_persistence():
    s = get_settings()
    if s.is_postgres:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
        from langgraph.store.postgres.aio import AsyncPostgresStore
        async with AsyncPostgresSaver.from_conn_string(s.pg_dsn()) as saver, AsyncPostgresStore.from_conn_string(s.pg_dsn()) as store:
            await saver.setup(); await store.setup()
            yield saver, store
    else:
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
        from langgraph.store.sqlite.aio import AsyncSqliteStore
        async with AsyncSqliteSaver.from_conn_string(str(s.processed / "checkpoints.sqlite")) as saver, AsyncSqliteStore.from_conn_string(str(s.processed / "store.sqlite")) as store:
            await saver.setup(); await store.setup()
            yield saver, store
