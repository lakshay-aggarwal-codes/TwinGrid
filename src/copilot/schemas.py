"""Request and response models for ``POST /api/copilot/ask`` (playbook section 8.4). Bounds are enforced here."""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .evidence import FRESHNESS, ORIGINS, SOURCES

MAX_QUESTION = 500
MAX_HISTORY = 6
MAX_ANSWER = 1500
MAX_ID = 64

ContextKind = Literal["alert", "signal", "model", "feature", "general"]
Source = Literal[SOURCES]  # type: ignore[valid-type]
Origin = Literal[ORIGINS]  # type: ignore[valid-type]
Freshness = Literal[FRESHNESS]  # type: ignore[valid-type]


class Context(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: ContextKind = "general"
    id: Optional[str] = Field(default=None, max_length=MAX_ID)


class HistoryItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["user", "assistant"]
    text: str = Field(max_length=MAX_QUESTION)


class AskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=MAX_QUESTION)
    context: Context = Field(default_factory=Context)
    history: list[HistoryItem] = Field(default_factory=list, max_length=MAX_HISTORY)

    @field_validator("question")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("question must not be blank")
        return v


class EvidenceItem(BaseModel):
    id: str
    source: Source
    entity: str
    field: str
    value: Any = None
    unit: Optional[str] = None
    observed_at: Optional[str] = None
    origin: Origin
    freshness: Freshness


class Link(BaseModel):
    label: str
    path: str


class Limits(BaseModel):
    provider_configured: bool = False


class AskResponse(BaseModel):
    request_id: str
    mode: Literal["rule_based", "llm"]
    answer: str = Field(max_length=MAX_ANSWER)
    evidence: list[EvidenceItem]
    unknowns: list[str]
    warnings: list[str]
    links: list[Link]
    limits: Limits
