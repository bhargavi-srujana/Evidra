"""Shared types and helpers for Phase 2 retrieval services."""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, Field

_WORD_RE = re.compile(r"[a-z0-9][a-z0-9\-]*")

# Minimal English stopword list for keyword decomposition (no NLP dep needed).
STOPWORDS = frozenset(
    {
        "a",
        "an",
        "the",
        "and",
        "or",
        "but",
        "of",
        "in",
        "on",
        "for",
        "to",
        "with",
        "does",
        "do",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "how",
        "what",
        "why",
        "when",
        "which",
        "who",
        "whom",
        "whose",
        "it",
        "its",
        "this",
        "that",
        "these",
        "those",
        "by",
        "from",
        "as",
        "at",
        "into",
        "than",
        "then",
        "so",
        "such",
        "no",
        "not",
        "can",
        "could",
        "should",
        "would",
        "will",
        "may",
        "might",
        "there",
        "their",
        "they",
        "them",
        "he",
        "she",
        "we",
        "you",
        "i",
    }
)


class SearchProviderError(RuntimeError):
    """Raised when a literature provider request fails (network, 4xx/5xx)."""


class RateLimitedError(SearchProviderError):
    """Raised on HTTP 429 / quota exhaustion so callers can fall back."""

    def __init__(
        self,
        provider: str,
        message: str = "Rate limit exceeded",
        retry_after: str | None = None,
    ) -> None:
        super().__init__(f"{provider}: {message}")
        self.provider = provider
        self.retry_after = retry_after


class RawPaper(BaseModel):
    """Provider-agnostic raw paper record (pre-LLM-extraction)."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    title: str
    snippet: str = ""
    authors: list[str] = Field(default_factory=list)
    year: int | None = Field(default=None, ge=1800, le=2100)
    venue: str | None = None
    doi: str | None = None
    link: str | None = None
    source: str = "unknown"

    def abstract_missing(self, min_len: int = 80) -> bool:
        """True when the snippet is absent or likely truncated."""
        return len(self.snippet.strip()) < min_len


def decompose_query(query: str) -> list[str]:
    """Reduce a natural-language question to keyword search terms.

    Lowercases, drops stopwords/punctuation, dedupes preserving order.
    Used for fallback queries when the verbatim question retrieves nothing.
    """
    terms: list[str] = []
    for token in _WORD_RE.findall(query.lower()):
        token = token.strip("-")
        if len(token) > 1 and token not in STOPWORDS and token not in terms:
            terms.append(token)
    return terms


def normalize_title(title: str) -> str:
    """Canonical title key for cross-provider dedupe/merge."""
    return re.sub(r"[^a-z0-9]+", "", title.lower())
