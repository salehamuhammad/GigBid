"""Request/response models. FastAPI turns these into OpenAPI; `make gen-api` turns that into the
typed TypeScript client the web app uses (D: no hand-written fetch types)."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class Credentials(BaseModel):
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", max_length=200)
    password: str = Field(min_length=8, max_length=200)
    name: str = Field(default="", max_length=120)


class UserOut(BaseModel):
    id: str
    email: str
    name: str
    onboarded: bool = False


class Session(BaseModel):
    token: str
    user: UserOut


class Settings(BaseModel):
    floor_rate: float = Field(default=30, ge=1, le=1000)
    target_rate: float = Field(default=45, ge=1, le=1000)
    min_project: float = Field(default=200, ge=0)
    connects_budget_week: int = Field(default=60, ge=0, le=1000)
    autonomy: Literal["suggest", "auto_skip"] = "suggest"
    strategy: Literal["evidence_first", "question_first"] = "evidence_first"
    experiment: bool = False
    categories: list[str] = Field(default_factory=list)
    min_budget: float = Field(default=0, ge=0)
    marketplace: Literal["gigsim", "upwork"] = "gigsim"
    onboarded: bool = False


class ProfileOut(BaseModel):
    owner: str
    settings: Settings
    upwork_connected: bool = False
    persona: dict[str, Any] | None = None


class OnboardIn(BaseModel):
    persona: str = Field(description="One of the bundled personas, or 'own' to start an empty portfolio you upload into")
    settings: Settings


class PersonaOut(BaseModel):
    id: str
    name: str
    headline: str
    skills: list[str]
    floor_rate: float
    target_rate: float
    min_project: float
    categories: list[str]


class SearchIn(BaseModel):
    query: str = Field(default="", max_length=200)
    category: str | None = None
    interval_minutes: int = Field(default=5, ge=1, le=1440)


class SearchOut(SearchIn):
    id: str
    enabled: bool = True
    last_run_at: float = 0


class JobSummary(BaseModel):
    job_id: str
    title: str
    category: str
    status: str
    fit: float | None = None
    risk: float | None = None
    action: str | None = None
    price: float | None = None
    connects_cost: int | None = None
    budget: dict[str, Any] = Field(default_factory=dict)
    posted_at: str | None = None
    note: str = ""
    flags: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)
    run_id: str | None = None
    updated_at: float = 0


class JobDetail(JobSummary):
    description: str = ""
    screening_questions: list[str] = Field(default_factory=list)
    client_id: str | None = None
    analysis: dict[str, Any] = Field(default_factory=dict)
    proposal: dict[str, Any] | None = None
    approval_id: str | None = None


class ApprovalOut(BaseModel):
    id: str
    kind: Literal["proposal", "message"]
    ref: str
    status: str
    payload: dict[str, Any]
    decision: dict[str, Any] = Field(default_factory=dict)
    created_at: float


class DecisionIn(BaseModel):
    action: Literal["approve", "edit", "reject", "regenerate"]
    edited_text: str | None = Field(default=None, max_length=6000)
    edited_bid: float | None = Field(default=None, gt=0)
    edited_answers: list[str] | None = None
    paragraph: int | None = Field(default=None, ge=0)
    reason: str | None = Field(default=None, max_length=500)


class Accepted(BaseModel):
    ok: bool = True
    run_id: str | None = None
    detail: str = ""


class ProposalCard(BaseModel):
    id: str
    job_id: str
    title: str
    category: str
    stage: str
    bid: float | None = None
    connects: int = 0
    strategy: str = ""
    conversation_id: str | None = None
    reject_reason: str = ""
    updated_at: float = 0


class ConversationOut(BaseModel):
    conversation_id: str
    job_id: str
    title: str
    status: str
    intent: str
    messages: list[dict[str, Any]]
    approval: ApprovalOut | None = None
    updated_at: float = 0


class RunOut(BaseModel):
    id: str
    kind: str
    ref: str
    status: str
    trace_id: str
    tokens: int
    cost_usd: float
    latency_ms: int
    started_at: float
    ended_at: float | None = None
    langsmith_url: str | None = None


class RunEventOut(BaseModel):
    id: int
    ts: float
    node: str
    type: str
    payload: dict[str, Any]


class RunDetail(RunOut):
    events: list[RunEventOut]
    nodes: list[dict[str, Any]] = Field(default_factory=list, description="per-node tokens, cost and latency")
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)


class MemoryItem(BaseModel):
    kind: str
    key: str
    description: str = ""
    rule: str = ""
    value: dict[str, Any] = Field(default_factory=dict)


class Health(BaseModel):
    status: Literal["ok", "degraded"]
    marketplace: dict[str, Any]
    servers: dict[str, bool]
    queued_jobs: int
    model_profile: str
    marketplace_mode: str
    worker: str


class Analytics(BaseModel):
    funnel: dict[str, int]
    reply_rate: float
    hire_rate: float
    connects_spent: int
    replies_per_10_connects: float
    by_category: list[dict[str, Any]]
    by_strategy: list[dict[str, Any]]
    cost_usd: float
    cost_per_job_usd: float
    tokens: int
    latency_ms_p50: int
    latency_ms_p95: int
    runs: int
    budgets: dict[str, Any]
    experiment: dict[str, Any] | None = None
