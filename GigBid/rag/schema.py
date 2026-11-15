from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Doc:
    id: str
    type: str                 # case_study | repo | review | proposal | cv | upload
    title: str
    text: str
    meta: dict = field(default_factory=dict)
    code: str = ""            # repos only


@dataclass
class Chunk:
    id: str
    doc_id: str
    text: str
    facet: str = "body"       # body | summary | readme | code
    meta: dict = field(default_factory=dict)


@dataclass
class Hit:
    doc_id: str
    score: float
    snippet: str = ""
    facets: dict = field(default_factory=dict)
    why: str = ""


@dataclass
class RetrievalResult:
    hits: list[Hit]
    per_requirement: dict[str, list[Hit]] = field(default_factory=dict)
    refused: bool = False
    phrasing: list[Hit] = field(default_factory=list)   # winning past proposals (V4), never used as proof
    debug: dict = field(default_factory=dict)
