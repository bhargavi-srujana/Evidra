"""Lightweight deterministic query normalization (no LLM, no quota cost).

Converts a raw natural-language research question into structured entities
*before* retrieval/extraction:

- ``neutral_search_query``: polarity-free terms for providers
  (e.g. "sleep duration academic performance").
- ``intervention``: the independent variable/factor under test
  (e.g. "sleeping less / sleep deprivation").
- ``outcome``: the target metric (e.g. "academic grades / GPA").
- ``expected_direction``: what the query hypothesizes —
  ``"positive"`` (intervention helps), ``"negative"`` (intervention harms),
  or ``"unclear"`` (no directional hypothesis).

Rule-based on purpose: parsing must never consume LLM quota or fail on
rate limits. Anything unrecognized falls back to the cleaned raw query with
empty intervention/outcome and ``"unclear"`` direction.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.services.common import decompose_query

_POSITIVE_VERBS = (
    "improve",
    "improves",
    "increase",
    "increases",
    "boost",
    "boosts",
    "enhance",
    "enhances",
    "benefit",
    "benefits",
)
_NEGATIVE_VERBS = (
    "reduce",
    "reduces",
    "decrease",
    "decreases",
    "lower",
    "lowers",
    "harm",
    "harms",
    "impair",
    "impairs",
    "worsen",
    "worsens",
)

# Direction modifiers stripped from the neutral provider query.
_POLARITY_WORDS = frozenset(
    {
        "less",
        "more",
        "fewer",
        "greater",
        "reduced",
        "increased",
        "reducing",
        "increasing",
        "deprived",
        "deprivation",
        "lack",
        "poor",
        "short",
        "long",
        "high",
        "low",
        "higher",
        "lower",
    }
)

_LEADING_FILLER_RE = re.compile(r"^(please\s+)?(tell me\s+)?", re.IGNORECASE)


@dataclass(frozen=True)
class ParsedQuery:
    """Structured form of a raw user query (see module docstring)."""

    neutral_search_query: str
    intervention: str
    outcome: str
    expected_direction: str  # "positive" | "negative" | "unclear"


def _clean(text: str) -> str:
    text = _LEADING_FILLER_RE.sub("", text.strip().lower())
    return text.rstrip("?").strip()


def _neutral(intervention: str, outcome: str) -> str:
    """Polarity-free provider terms from the parsed entities."""
    terms = decompose_query(f"{intervention} {outcome}")
    kept = [t for t in terms if t not in _POLARITY_WORDS]
    return " ".join(kept)


def parse_query(raw_query: str) -> ParsedQuery:
    """Normalize a raw research question into structured entities.

    Never raises: unrecognized shapes fall back to the cleaned raw query
    with empty intervention/outcome and "unclear" direction.
    """
    query = _clean(raw_query or "")
    if not query:
        return ParsedQuery(
            neutral_search_query="",
            intervention="",
            outcome="",
            expected_direction="unclear",
        )

    positive = "|".join(_POSITIVE_VERBS)
    negative = "|".join(_NEGATIVE_VERBS)

    patterns: tuple[tuple[str, str, str, str], ...] = (
        # "does grades improve by sleeping less" (outcome-first passive)
        (
            rf"^(?:does|do|can)\s+(?P<first>.+?)\s+(?:{positive})\s+by\s+(?P<second>.+)$",
            "outcome",
            "intervention",
            "positive",
        ),
        # "does sleeping less improve grades" (active, positive verb)
        (
            rf"^(?:does|do|can)\s+(?P<first>.+?)\s+(?:{positive})\s+(?P<second>.+)$",
            "intervention",
            "outcome",
            "positive",
        ),
        # "does sleeping less reduce grades" (active, negative verb)
        (
            rf"^(?:does|do|can)\s+(?P<first>.+?)\s+(?:{negative})\s+(?P<second>.+)$",
            "intervention",
            "outcome",
            "negative",
        ),
        # "what is the effect of X on Y" / "effect of X on Y"
        (
            r"^(?:what is|what are|what's|whats)\s+the\s+effects?\s+of\s+(?P<first>.+?)\s+on\s+(?P<second>.+)$",
            "intervention",
            "outcome",
            "unclear",
        ),
        (
            r"^effects?\s+of\s+(?P<first>.+?)\s+on\s+(?P<second>.+)$",
            "intervention",
            "outcome",
            "unclear",
        ),
        # "how does X affect/impact/influence Y"
        (
            r"^how\s+does\s+(?P<first>.+?)\s+(?:affect|affects|impact|impacts|influence|influences)\s+(?P<second>.+)$",
            "intervention",
            "outcome",
            "unclear",
        ),
        # "is there a link between X and Y"
        (
            r"^(?:is|are)\s+there\s+(?:a|an|any)?\s*(?:link|association|correlation|relationship|connection)\s+between\s+(?P<first>.+?)\s+and\s+(?P<second>.+)$",
            "intervention",
            "outcome",
            "unclear",
        ),
    )
    for regex, first_role, second_role, direction in patterns:
        match = re.match(regex, query)
        if not match:
            continue
        first, second = match.group("first").strip(), match.group("second").strip()
        intervention = first if first_role == "intervention" else second
        outcome = second if second_role == "outcome" else first
        if not intervention or not outcome:
            continue
        return ParsedQuery(
            neutral_search_query=_neutral(intervention, outcome) or query,
            intervention=intervention,
            outcome=outcome,
            expected_direction=direction,
        )

    # Fallback: keyword query, no directional hypothesis.
    return ParsedQuery(
        neutral_search_query=" ".join(decompose_query(query)) or query,
        intervention="",
        outcome="",
        expected_direction="unclear",
    )


__all__ = ["ParsedQuery", "parse_query"]
