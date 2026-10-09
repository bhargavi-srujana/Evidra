"""Study metadata schemas (Pydantic v2, strict)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class StudyDesign(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    population: str | None = Field(default=None)
    sample_size: str | None = Field(default=None)
    intervention: str | None = Field(default=None)
    control: str | None = Field(default=None)
    task_type: str | None = Field(default=None)
    measurement_metric: str | None = Field(default=None)
    study_duration: str | None = Field(default=None)
    study_type: str | None = Field(default=None)


class Author(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str
    affiliation: str | None = Field(default=None)


class Study(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    study_id: str
    title: str
    authors: list[Author]
    # Nullable: unknown publication years stay null so real and missing
    # years remain distinct (never fabricated as the current year).
    year: int | None = Field(default=None, ge=1800, le=2100)
    venue: str | None = Field(default=None)
    doi: str | None = Field(default=None)
    abstract: str
    url: str | None = Field(default=None)
    design: StudyDesign = Field(default_factory=StudyDesign)
    # True when PICO/claims came from the deterministic heuristic fallback
    # (quota-exhausted / LLM-unconfigured) instead of the LLM. Fallback
    # records are served to the caller but never frozen into search_cache.
    is_fallback: bool = False
