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

# Group-comparison questions ("do men sleep more than women"): the tested
# factor is group A *relative to* group B, so opposite questions must anchor
# opposite verdicts instead of collapsing to the same unanchored query.
_COMPARATIVE_POSITIVE = frozenset(
    {"more", "greater", "longer", "better", "higher", "faster", "stronger", "larger"}
)
_COMPARATIVE_NEGATIVE = frozenset(
    {"less", "fewer", "shorter", "worse", "lower", "slower", "weaker", "smaller"}
)
_COMPARATIVE_RE = re.compile(
    r"^(?:does|do|can)\s+(?P<group_a>.+?)\s+(?P<topic>.+?)\s+"
    r"(?P<comp>more|less|fewer|greater|longer|shorter|better|worse|higher|lower|faster|slower|stronger|weaker|larger|smaller)\s+"
    r"(?:than\s+(?P<than_b>.+)|when\s+compared\s+to\s+(?P<compared_b>.+))$",
    re.IGNORECASE,
)

_LEADING_FILLER_RE = re.compile(r"^(please\s+)?(tell me\s+)?", re.IGNORECASE)


@dataclass(frozen=True)
class ParsedQuery:
    """Structured form of a raw user query (see module docstring)."""

    neutral_search_query: str
    intervention: str
    outcome: str
    expected_direction: str  # "positive" | "negative" | "unclear"
    # Natural-language question used as the LLM direction anchor. Empty means
    # the extractor falls back to the templated "Does {intervention} increase
    # {outcome}?" form.
    anchor_question: str = ""


def _clean(text: str) -> str:
    text = _LEADING_FILLER_RE.sub("", text.strip().lower())
    return text.rstrip("?").strip()


def _neutral(intervention: str, outcome: str) -> str:
    """Polarity-free provider terms from the parsed entities."""
    terms = decompose_query(f"{intervention} {outcome}")
    kept = [t for t in terms if t not in _POLARITY_WORDS]
    return " ".join(kept)


def _comparative_neutral(group_a: str, topic: str, group_b: str) -> str:
    """Order-insensitive provider terms for group-comparison questions.

    "do men sleep more than women" and "do women sleep more when compared to
    men" must retrieve the SAME corpus (the direction anchor, not the
    retrieval query, carries the A-vs-B polarity). Sorting the polarity-free
    terms makes opposite phrasings collapse to one canonical query, so live
    providers return the same papers and opposite anchors yield mirrored
    verdicts instead of different corpora.
    """
    terms = decompose_query(f"{group_a} {topic} {group_b}")
    kept = sorted({t for t in terms if t not in _POLARITY_WORDS})
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

    # "do men sleep more than women" / "... more when compared to women":
    # group A tested relative to group B. Runs AFTER the verb patterns so
    # "does X improve Y more than Z" keeps its verb-anchored parse.
    comp_match = _COMPARATIVE_RE.match(query)
    if comp_match:
        group_a = comp_match.group("group_a").strip()
        topic = comp_match.group("topic").strip()
        comp = comp_match.group("comp").strip().lower()
        group_b = (comp_match.group("than_b") or comp_match.group("compared_b") or "").strip()
        if group_a and topic and group_b:
            intervention = f"{group_a} (compared to {group_b})"
            direction = "negative" if comp in _COMPARATIVE_NEGATIVE else "positive"
            return ParsedQuery(
                neutral_search_query=_comparative_neutral(group_a, topic, group_b) or query,
                intervention=intervention,
                outcome=topic,
                expected_direction=direction,
                # Natural phrasing for the LLM anchor: the templated
                # "Does {intervention} increase {outcome}?" form renders
                # Comparatives ungrammatically ("Does men (compared to women)
                # increase sleep?"), which pushes the model toward "unclear".
                anchor_question=f"Do {group_a} {topic} {comp} than {group_b}?",
            )

    # Fallback: keyword query, no directional hypothesis. The raw question
    # still anchors the LLM (better than the vacuous "studied intervention"
    # template) — exactly when guidance is needed most.
    cleaned_fallback = query if query else (raw_query or "").strip()
    return ParsedQuery(
        neutral_search_query=" ".join(decompose_query(query)) or query,
        intervention="",
        outcome="",
        expected_direction="unclear",
        anchor_question=f"{cleaned_fallback}?" if cleaned_fallback else "",
    )


# --- LLM parser fallback (shapes the regexes miss) ---
# One small JSON call per unrecognized question shape, cached in-process by
# cleaned query so repeats cost nothing. Gated by the LLM_QUERY_PARSER flag
# and skipped when no LLM key is configured. Any failure (transport, shape,
# validation) returns the rule-based fallback above — parsing never breaks
# search and never burns more than one call per novel shape.
LLM_PARSER_VERSION = "1.0.0"
_LLM_PARSE_CACHE: dict[str, ParsedQuery] = {}
_LLM_PARSE_CACHE_MAX = 512
_ENTITY_MAX_CHARS = 200
_VALID_DIRECTIONS = ("positive", "negative", "unclear")

LLM_PARSER_SYSTEM_PROMPT = (
    "You extract structured entities from a research question. "
    "Analyze ONLY the question inside <user_query> tags. "
    "Return ONLY a JSON object with exactly these keys: "
    '"intervention" (the tested factor or group, with comparison context, '
    'or "" if none), '
    '"outcome" (the measured effect or topic, or "" if none), '
    '"expected_direction" (one of "positive", "negative", "unclear"), '
    '"neutral_search_query" (polarity-free keyword terms for literature search). '
    "NEVER guess entities the question does not state: use empty strings "
    'and "unclear" instead of inventing. No markdown, no commentary.'
)


def clear_llm_query_cache() -> None:
    """Drop the in-process LLM parse cache (tests, key rotation)."""
    _LLM_PARSE_CACHE.clear()


def _coerce_llm_parse(data: object, cleaned_query: str) -> ParsedQuery | None:
    """Validate the LLM parse payload; None when unusable (rule fallback wins)."""
    if not isinstance(data, dict):
        return None
    intervention = str(data.get("intervention") or "").strip()[:_ENTITY_MAX_CHARS]
    outcome = str(data.get("outcome") or "").strip()[:_ENTITY_MAX_CHARS]
    direction = str(data.get("expected_direction") or "").strip().lower()
    if direction not in _VALID_DIRECTIONS:
        direction = "unclear"
    neutral = str(data.get("neutral_search_query") or "").strip()
    if not neutral:
        neutral = " ".join(decompose_query(cleaned_query)) or cleaned_query
    if not intervention and not outcome:
        return None
    return ParsedQuery(
        neutral_search_query=_neutral(intervention, outcome) or neutral,
        intervention=intervention,
        outcome=outcome,
        expected_direction=direction,
        anchor_question=f"{cleaned_query}?" if cleaned_query else "",
    )


async def aparse_query(raw_query: str) -> ParsedQuery:
    """Rule-based parse, escalating to the LLM fallback on misses. Never raises.

    Shapes the regexes recognize cost zero quota. Anything else (is/are,
    which/who, why, superlatives, conversational queries) gets one cached
    LLM parse when enabled and configured; failures return the rule-based
    keyword fallback.
    """
    rule_parsed = parse_query(raw_query)
    if rule_parsed.intervention or rule_parsed.outcome:
        return rule_parsed
    cleaned = _clean(raw_query or "")
    if not cleaned:
        return rule_parsed
    cached = _LLM_PARSE_CACHE.get(cleaned)
    if cached is not None:
        return cached
    try:
        from app.core.config import get_settings
        from app.services.extraction import (
            _chat_json,
            _sanitize_prompt_span,
            is_llm_configured,
        )

        if not get_settings().LLM_QUERY_PARSER or not is_llm_configured():
            return rule_parsed
        user = (
            "Extract entities from this research question.\n\n<user_query>\n"
            f"{_sanitize_prompt_span(cleaned)}\n</user_query>"
        )
        data = await _chat_json(LLM_PARSER_SYSTEM_PROMPT, user)
        llm_parsed = _coerce_llm_parse(data, cleaned)
    except Exception:  # noqa: BLE001 - parser fallback must never break search
        return rule_parsed
    if llm_parsed is None:
        # LLM returned nothing usable: do NOT cache the keyword fallback, or
        # one transient outage/malformed payload would freeze this question
        # on the fallback until the cache clears.
        return rule_parsed
    if len(_LLM_PARSE_CACHE) >= _LLM_PARSE_CACHE_MAX:
        # Evict oldest first (dicts preserve insertion order), not clear-all.
        _LLM_PARSE_CACHE.pop(next(iter(_LLM_PARSE_CACHE)))
    _LLM_PARSE_CACHE[cleaned] = llm_parsed
    return llm_parsed


__all__ = [
    "ParsedQuery",
    "aparse_query",
    "clear_llm_query_cache",
    "parse_query",
]
