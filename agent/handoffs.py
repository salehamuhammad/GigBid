"""Typed hand-offs. Agents exchange these objects -- never free text -- for anything a later
step decides on (C3)."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class JobSpec(BaseModel):
    job_id: str
    title: str
    summary: str = ""
    category: str = ""
    deliverables: list[str] = Field(default_factory=list)
    required_skills: list[str] = Field(default_factory=list)
    requirements: list[str] = Field(default_factory=list, description="One short sentence per distinct requirement")
    budget_type: Literal["fixed", "hourly", "unknown"] = "unknown"
    budget_min: float | None = None
    budget_max: float | None = None
    timeline_weeks: float | None = None
    screening_questions: list[str] = Field(default_factory=list)
    hidden_needs: list[str] = Field(default_factory=list)


class RiskFlag(BaseModel):
    code: str
    severity: Literal["low", "medium", "high"] = "medium"
    evidence: str = ""


class RiskReport(BaseModel):
    score: float = Field(ge=0, le=1)
    level: Literal["low", "medium", "high"] = "low"
    flags: list[RiskFlag] = Field(default_factory=list)
    client_quality: float = Field(default=0.5, ge=0, le=1)
    is_scam: bool = False
    injection_detected: bool = False
    explanation: str = ""


class EvidenceItem(BaseModel):
    id: str
    type: str = ""
    title: str = ""
    source: str = ""
    date: str = ""
    outcome: str = ""
    project: str = ""
    skills: list[str] = Field(default_factory=list)
    snippet: str = ""
    score: float = 0.0


class RequirementMatch(BaseModel):
    requirement: str
    covered: bool = False
    strength: float = Field(default=0, ge=0, le=1)
    evidence: list[EvidenceItem] = Field(default_factory=list)


class FitReport(BaseModel):
    score: float = Field(ge=0, le=1)
    matrix: list[RequirementMatch] = Field(default_factory=list)
    matched_skills: list[str] = Field(default_factory=list)
    missing_skills: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)
    retrieval_refused: bool = False


class BidDecision(BaseModel):
    action: Literal["skip", "watch", "bid"]
    reasons: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.5, ge=0, le=1)


class PriceQuote(BaseModel):
    bid_amount: float = Field(gt=0)
    bid_type: Literal["fixed", "hourly"] = "fixed"
    currency: str = "USD"
    floor: float = 0
    market_low: float | None = None
    market_median: float | None = None
    market_high: float | None = None
    connects_cost: int = 0
    connects_balance: int | None = None
    expected_value_usd: float = 0
    worth_connects: bool = True
    rationale: list[str] = Field(default_factory=list)


class Claim(BaseModel):
    text: str
    evidence_ids: list[str] = Field(default_factory=list)
    label: Literal["supported", "partly_supported", "unsupported", "not_a_claim", "unchecked"] = "unchecked"
    reason: str = ""


class ScreeningAnswer(BaseModel):
    question: str
    answer: str
    evidence_ids: list[str] = Field(default_factory=list)


class ProposalDraft(BaseModel):
    job_id: str
    cover_letter: str
    claims: list[Claim] = Field(default_factory=list)
    screening_answers: list[ScreeningAnswer] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    strategy: str = "evidence_first"
    revision: int = 0


class VerificationReport(BaseModel):
    claims: list[Claim] = Field(default_factory=list)
    total_claims: int = 0
    unsupported_before: int = 0
    unsupported_after: int = 0
    removed: list[str] = Field(default_factory=list)


class Critique(BaseModel):
    verdict: Literal["approve", "revise"]
    grounding: float = Field(default=1, ge=0, le=1)
    personalisation: float = Field(default=1, ge=0, le=1)
    length_ok: bool = True
    reasons: list[str] = Field(default_factory=list)
    instructions: list[str] = Field(default_factory=list)


class Violation(BaseModel):
    rule: str
    severity: Literal["block", "redact", "warn"]
    excerpt: str = ""
    description: str = ""


class ComplianceVerdict(BaseModel):
    status: Literal["pass", "redacted", "blocked"]
    violations: list[Violation] = Field(default_factory=list)
    cleaned_text: str = ""
    reason: str = ""


class IntentReport(BaseModel):
    intent: Literal["question", "negotiation", "interview_request", "scam_signal", "other"]
    confidence: float = Field(default=0.5, ge=0, le=1)
    signals: list[str] = Field(default_factory=list)
    injection_detected: bool = False


class ReplyDraft(BaseModel):
    thread_id: str
    text: str
    intent: str = "other"
    slots: list[dict] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)


class ApprovalDecision(BaseModel):
    action: Literal["approve", "edit", "reject", "regenerate"]
    paragraph: int | None = Field(default=None, ge=0, description="regenerate: index of the paragraph to rewrite")
    edited_text: str | None = None
    edited_bid: float | None = Field(default=None, gt=0)
    edited_answers: list[str] | None = None
    reason: str | None = None
