"""Application database (SQLAlchemy 2). Postgres in docker/deploy, SQLite for a bare local run.
Every table that holds user data has `user_id`, and every query in the routers filters on it (E4)."""
from __future__ import annotations

import time
import uuid
from contextlib import contextmanager

from sqlalchemy import JSON, Float, Index, Integer, String, Text, UniqueConstraint, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from agent.settings import get_settings


def now() -> float: return time.time()
def uid() -> str: return uuid.uuid4().hex[:16]


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    email: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120), default="")
    password_hash: Mapped[str] = mapped_column(String(300))
    created_at: Mapped[float] = mapped_column(Float, default=now)


class Profile(Base):
    __tablename__ = "profiles"
    user_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    owner: Mapped[str] = mapped_column(String(64), default="ai_engineer")       # persona id, or "own-<user>"
    settings: Mapped[dict] = mapped_column(JSON, default=dict)


class SavedSearch(Base):
    __tablename__ = "saved_searches"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(String(32), index=True)
    query: Mapped[str] = mapped_column(String(200), default="")
    category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    interval_minutes: Mapped[int] = mapped_column(Integer, default=5)
    enabled: Mapped[int] = mapped_column(Integer, default=1)
    last_run_at: Mapped[float] = mapped_column(Float, default=0)


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (UniqueConstraint("user_id", "job_id"), Index("ix_jobs_user_status", "user_id", "status"))
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(32))
    job_id: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(300), default="")
    category: Mapped[str] = mapped_column(String(64), default="")
    signature: Mapped[str] = mapped_column(String(32), default="", index=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(32), default="new")
    fit: Mapped[float | None] = mapped_column(Float, nullable=True)
    risk: Mapped[float | None] = mapped_column(Float, nullable=True)
    action: Mapped[str | None] = mapped_column(String(16), nullable=True)
    price: Mapped[float | None] = mapped_column(Float, nullable=True)
    connects_cost: Mapped[int | None] = mapped_column(Integer, nullable=True)
    analysis: Mapped[dict] = mapped_column(JSON, default=dict)
    run_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[float] = mapped_column(Float, default=now)
    updated_at: Mapped[float] = mapped_column(Float, default=now)


class Proposal(Base):
    __tablename__ = "proposals"
    __table_args__ = (UniqueConstraint("user_id", "job_id"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(String(32), index=True)
    job_id: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(300), default="")
    category: Mapped[str] = mapped_column(String(64), default="")
    stage: Mapped[str] = mapped_column(String(24), default="drafted")     # drafted submitted viewed replied interview hired lost rejected
    draft: Mapped[dict] = mapped_column(JSON, default=dict)
    bid: Mapped[float | None] = mapped_column(Float, nullable=True)
    connects: Mapped[int] = mapped_column(Integer, default=0)
    strategy: Mapped[str] = mapped_column(String(32), default="evidence_first")
    marketplace_proposal_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    conversation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reject_reason: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[float] = mapped_column(Float, default=now)
    updated_at: Mapped[float] = mapped_column(Float, default=now)


class Run(Base):
    __tablename__ = "runs"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(String(32), index=True)
    kind: Mapped[str] = mapped_column(String(16))                          # bid | conversation | scout
    ref: Mapped[str] = mapped_column(String(64), default="")
    thread_id: Mapped[str] = mapped_column(String(160), default="")
    status: Mapped[str] = mapped_column(String(24), default="running")      # running waiting_approval done failed queued
    trace_id: Mapped[str] = mapped_column(String(64), default="")
    langsmith_run_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    summary: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[float] = mapped_column(Float, default=now)
    ended_at: Mapped[float | None] = mapped_column(Float, nullable=True)


class RunEvent(Base):
    __tablename__ = "run_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(32), index=True)
    user_id: Mapped[str] = mapped_column(String(32))
    ts: Mapped[float] = mapped_column(Float, default=now)
    node: Mapped[str] = mapped_column(String(48), default="")
    type: Mapped[str] = mapped_column(String(24), default="")
    payload: Mapped[dict] = mapped_column(JSON, default=dict)


class Approval(Base):
    __tablename__ = "approvals"
    id: Mapped[str] = mapped_column(String(200), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(32), index=True)
    kind: Mapped[str] = mapped_column(String(16))                          # proposal | message
    thread_id: Mapped[str] = mapped_column(String(160), index=True)
    ref: Mapped[str] = mapped_column(String(64), default="")
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="pending")      # pending processing approved rejected edited superseded
    decision: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[float] = mapped_column(Float, default=now)
    decided_at: Mapped[float | None] = mapped_column(Float, nullable=True)


class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = (UniqueConstraint("user_id", "conversation_id"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(String(32), index=True)
    conversation_id: Mapped[str] = mapped_column(String(64))
    job_id: Mapped[str] = mapped_column(String(64), default="")
    title: Mapped[str] = mapped_column(String(300), default="")
    messages: Mapped[list] = mapped_column(JSON, default=list)
    intent: Mapped[str] = mapped_column(String(32), default="")
    status: Mapped[str] = mapped_column(String(24), default="open")         # open needs_reply awaiting_approval replied flagged
    updated_at: Mapped[float] = mapped_column(Float, default=now)


class OAuthToken(Base):
    __tablename__ = "oauth_tokens"
    user_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    provider: Mapped[str] = mapped_column(String(32), primary_key=True)
    encrypted: Mapped[str] = mapped_column(Text)                           # Fernet ciphertext; never logged
    updated_at: Mapped[float] = mapped_column(Float, default=now)


class KV(Base):
    __tablename__ = "kv"
    user_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON, default=dict)


_engine = None
_Session = None


def engine():
    global _engine, _Session
    if _engine is None:
        url = get_settings().database_url
        kw = {"connect_args": {"check_same_thread": False, "timeout": 30}} if url.startswith("sqlite") else {"pool_pre_ping": True}
        _engine = create_engine(url, **kw)
        _Session = sessionmaker(_engine, expire_on_commit=False)
        Base.metadata.create_all(_engine)
    return _engine


@contextmanager
def session():
    engine()
    s = _Session()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback(); raise
    finally:
        s.close()


def kv_get(s, user_id: str, key: str, default=None):
    row = s.get(KV, (user_id, key))
    return row.value if row else default


def kv_set(s, user_id: str, key: str, value) -> None:
    row = s.get(KV, (user_id, key))
    if row: row.value = value
    else: s.add(KV(user_id=user_id, key=key, value=value))
