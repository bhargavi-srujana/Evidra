"""Comparison / contradiction schemas (Pydantic v2, strict)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models.claim import EffectDirection

ImpactLevel = Literal["HIGH", "MEDIUM", "LOW"]


class MethodologicalDifference(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    dimension: str = Field(min_length=1)
    study_a_value: str | None = Field(default=None)
    study_b_value: str | None = Field(default=None)
    impact_level: ImpactLevel


class PairwiseContradiction(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    study_a_id: str
    study_b_id: str
    observed_difference: str = Field(min_length=1)
    hypothesized_explanation: str = Field(min_length=1)
    method_differences: list[MethodologicalDifference] = Field(default_factory=list)


class EvidenceSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total_studies: int = Field(ge=0)
    positive_count: int = Field(ge=0)
    conditional_count: int = Field(ge=0)
    negative_count: int = Field(ge=0)
    # Claims whose direction could not be determined (thin text, hedged
    # language). Counted explicitly so every retrieved study's finding is
    # accounted for in the overview instead of silently vanishing.
    unclear_count: int = Field(default=0, ge=0)
    key_gaps: list[str] = Field(default_factory=list)


class ClaimCluster(BaseModel):
    """Semantic group of claims about one high-level topic."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    cluster_id: str
    topic: str = Field(min_length=1)
    claim_ids: list[str]
    dominant_direction: EffectDirection | None = None


class ComparisonMatrix(BaseModel):
    """Full Phase 3 payload: clusters + contradictions + corpus gaps."""

    model_config = ConfigDict(extra="forbid")

    clusters: list[ClaimCluster] = Field(default_factory=list)
    contradictions: list[PairwiseContradiction] = Field(default_factory=list)
    summary: EvidenceSummary
    gaps: list[str] = Field(default_factory=list)
