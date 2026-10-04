"""Claim extraction schemas (Pydantic v2, strict)."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class EffectDirection(str, Enum):
    INCREASES = "increases"
    DECREASES = "decreases"
    NO_EFFECT = "no_effect"
    CONDITIONAL = "conditional"
    UNCLEAR = "unclear"


class Claim(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, use_enum_values=False)

    claim_id: str
    study_id: str
    text: str = Field(min_length=1)
    effect_direction: EffectDirection
    confidence_score: float = Field(ge=0.0, le=1.0)
    evidence_span: str | None = Field(default=None)
