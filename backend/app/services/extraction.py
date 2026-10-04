"""Structured PICO + claim extraction via an OpenAI-compatible LLM.

Loads versioned prompts from `app/prompts/*.json`, calls the chat-completions
API with strict-JSON mode, and validates output with Pydantic. Zero
hallucination is enforced by prompt contract + null-normalization: anything
not explicitly in the text becomes None / skipped, never invented.

All entry points degrade gracefully: LLM unconfigured or failing returns a
"Not reported" fallback design / no claims so retrieval still succeeds.
`extract_study_unified` is the preferred single-call path (PICO + claims in
one request); the two legacy single-purpose extractors are kept for
backward compatibility.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from functools import lru_cache
from pathlib import Path
from typing import Any

from openai import AsyncOpenAI

from app.core.config import get_settings
from app.models.claim import Claim
from app.models.study import StudyDesign

logger = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"
STUDY_PROMPT_FILE = "extract_study.json"
CLAIMS_PROMPT_FILE = "extract_claims.json"
UNIFIED_PROMPT_FILE = "extract_study_unified.json"
MAX_PAPER_CHARS = 6000
PLACEHOLDER_API_KEY = "sk-change-me"

# Concurrency guard: at most 2 LLM requests in flight at once, so a 10-15
# paper search fans out in controlled batches instead of hammering the
# provider. This is the single choke point — every LLM call flows through
# _chat_json, so PICO, claim, topic-label, and contradiction-refinement calls
# are all covered even when callers dispatch with unbounded asyncio.gather.
MAX_CONCURRENT_LLM_REQUESTS = 2
LLM_SEMAPHORE = asyncio.Semaphore(MAX_CONCURRENT_LLM_REQUESTS)
# Back-compat alias matching the commonly suggested snippet shape.
SEMAPHORE = LLM_SEMAPHORE

# Throttling: serialize LLM requests so only ONE hits the API at a time, with
# a minimum pause between request starts (LLM_MIN_INTERVAL_SECONDS). The lock
# is held for the whole request, so starts are spaced >= interval AND never
# overlap; slow requests consume part of the interval instead of stacking a
# full sleep on top. Regimes via env:
#   LLM_MIN_INTERVAL_SECONDS=12 (default) -> strict free-tier pacing, ~5 RPM
#     (Gemini free tier: 5 req/min, 20 req/day per model).
#   LLM_MIN_INTERVAL_SECONDS=4 -> 15 RPM providers.
#   LLM_MIN_INTERVAL_SECONDS=1 -> light "1s pause between batches" regime.
#   LLM_MIN_INTERVAL_SECONDS=0 -> pacing off (paid tier); the semaphore burst
#     cap above (2 at a time) governs instead.
EXTRACTION_LOCK = asyncio.Lock()
_last_llm_start: float = 0.0

# Matches provider "retry in ..." hints, e.g. "Please retry in 7.05s." or
# "Please retry in 17h57m15.1s." (Gemini daily-quota lockout).
_RETRY_AFTER_RE = re.compile(r"retry in (?:(\d+)h)?(?:(\d+)m)?([\d.]+)s", re.IGNORECASE)
# Fallback backoff base when the error carries no usable retry hint.
_RETRY_FALLBACK_BASE_SECONDS = 5.0

# Values that mean "not stated" -> normalized to None (never stored as text).
_NULL_LITERALS = frozenset(
    {
        "",
        "null",
        "none",
        "n/a",
        "na",
        "unknown",
        "not reported",
        "not stated",
        "not specified",
        "not available",
        "not provided",
        "not mentioned",
        "unclear",
        "not applicable",
    }
)

_client: AsyncOpenAI | None = None


@lru_cache(maxsize=4)
def load_prompt(filename: str) -> dict[str, Any]:
    """Load (and cache) a versioned prompt definition from `app/prompts/`."""
    path = PROMPTS_DIR / filename
    return json.loads(path.read_text(encoding="utf-8"))


def is_llm_configured() -> bool:
    """True when a non-placeholder OpenAI-compatible key is set."""
    key = (get_settings().OPENAI_API_KEY or "").strip()
    return bool(key) and key != PLACEHOLDER_API_KEY


def _get_client() -> AsyncOpenAI | None:
    """Shared async LLM client, or None when unconfigured (no hard failure)."""
    global _client
    if _client is not None:
        return _client
    settings = get_settings()
    if not is_llm_configured():
        return None
    _client = AsyncOpenAI(
        base_url=settings.OPENAI_BASE_URL,
        api_key=settings.OPENAI_API_KEY,
        timeout=60.0,
        # No blind SDK retries: _chat_create() below retries 429/503 itself
        # with quota-aware delays (honoring the server's retry hint). Blind
        # retries just burn free-tier quota faster.
        max_retries=0,
    )
    return _client


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        lines = lines[1:]  # drop opening fence (``` or ```json)
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


def _norm_opt(value: object) -> str | None:
    """Normalize missing-value literals to None; strip everything else."""
    if value is None:
        return None
    text = str(value).strip()
    if text.lower().rstrip(".") in _NULL_LITERALS:
        return None
    return text or None


def _build_paper_text(title: str, abstract: str) -> str:
    text = f"Title: {title.strip()}\nAbstract: {(abstract or '').strip()}"
    return text[:MAX_PAPER_CHARS]


def _throttle_interval() -> float:
    """Configured minimum gap between LLM request starts; <=0 disables pacing."""
    try:
        return max(0.0, float(get_settings().LLM_MIN_INTERVAL_SECONDS))
    except (TypeError, ValueError):
        return 0.0


def _parse_retry_delay_seconds(message: str) -> float | None:
    """Extract the server's "retry in ..." hint in seconds, else None."""
    match = _RETRY_AFTER_RE.search(message or "")
    if not match:
        return None
    hours = int(match.group(1) or 0)
    minutes = int(match.group(2) or 0)
    seconds = float(match.group(3) or 0)
    return hours * 3600 + minutes * 60 + seconds


def _is_retryable_llm_error(exc: Exception) -> bool:
    """True for transient rate-limit/overload errors (429/503), never for
    contract errors such as a rejected response_format."""
    text = str(exc).lower()
    if "response_format" in text:
        return False
    status = getattr(exc, "status_code", None)
    if status in (429, 503):
        return True
    return (
        "429" in text
        or "503" in text
        or "rate limit" in text
        or "quota" in text
        or "overloaded" in text
        or "unavailable" in text
    )


def _retry_delay_for(exc: Exception, attempt: int) -> float | None:
    """Seconds to wait before retrying, or None to fail fast.

    Honors the server's retry hint when it fits inside
    LLM_MAX_RETRY_DELAY_SECONDS; a huge hint (e.g. an 18h daily-quota
    lockout) returns None so the call fails fast and extraction degrades
    gracefully instead of hanging. Without a usable hint, exponential
    backoff (5s, 10s, ...) applies, capped the same way.
    """
    cap = float(get_settings().LLM_MAX_RETRY_DELAY_SECONDS)
    hinted = _parse_retry_delay_seconds(str(exc))
    if hinted is not None:
        return hinted if 0 < hinted <= cap else None
    fallback = _RETRY_FALLBACK_BASE_SECONDS * (2**attempt)
    return fallback if fallback <= cap else None


async def _chat_create(client: Any, model: str, messages: list[dict[str, str]], use_json: bool) -> Any:
    """One chat-completions call with quota-aware retries on 429/503."""
    max_retries = max(0, int(get_settings().LLM_MAX_RETRIES))
    last_exc: Exception | None = None
    for attempt in range(1 + max_retries):
        try:
            kwargs: dict[str, Any] = {"model": model, "messages": messages, "temperature": 0}
            if use_json:
                kwargs["response_format"] = {"type": "json_object"}
            return await client.chat.completions.create(**kwargs)
        except Exception as exc:  # noqa: BLE001 - inspected for retryability
            last_exc = exc
            if attempt >= max_retries or not _is_retryable_llm_error(exc):
                raise
            delay = _retry_delay_for(exc, attempt)
            if delay is None:
                raise
            logger.warning(
                "LLM rate-limited (%s); retry %d/%d in %.1fs",
                type(exc).__name__,
                attempt + 1,
                max_retries,
                delay,
            )
            await asyncio.sleep(delay)
    assert last_exc is not None  # unreachable; keeps type-checkers happy
    raise last_exc


async def _do_chat_json(system_prompt: str, user_prompt: str) -> Any:
    """Single chat completion parsed as JSON. Raises on transport/parse failure."""
    settings = get_settings()
    client = _get_client()
    if client is None:
        raise RuntimeError("LLM is not configured (OPENAI_API_KEY missing)")
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    try:
        response = await _chat_create(
            client, settings.OPENAI_MODEL, messages, use_json=True
        )
    except Exception as exc:
        # Some OpenAI-compatible gateways reject response_format; retry plain.
        if "response_format" not in str(exc).lower():
            raise
        logger.info("LLM gateway rejected response_format; retrying without it")
        response = await _chat_create(
            client, settings.OPENAI_MODEL, messages, use_json=False
        )
    content = (response.choices[0].message.content or "").strip()
    if not content:
        raise ValueError("LLM returned empty content")
    return json.loads(_strip_fences(content))


async def _chat_json(system_prompt: str, user_prompt: str) -> Any:
    """Chat completion parsed as JSON. Raises on transport/parse failure.

    Guarded twice: free-tier pacing (EXTRACTION_LOCK + minimum interval
    between starts, default 12s for 5 RPM providers) keeps 10-15 parallel
    study extractions from tripping 429s, and transient 429/503s are retried
    honoring the server's retry hint; with pacing disabled the LLM_SEMAPHORE
    burst cap (MAX_CONCURRENT_LLM_REQUESTS) applies instead.
    """
    global _last_llm_start
    interval = _throttle_interval()
    if interval > 0:
        async with EXTRACTION_LOCK:
            now = time.monotonic()
            wait = _last_llm_start + interval - now
            if wait > 0:
                await asyncio.sleep(wait)
            _last_llm_start = time.monotonic()
            return await _do_chat_json(system_prompt, user_prompt)
    async with LLM_SEMAPHORE:
        return await _do_chat_json(system_prompt, user_prompt)


DESIGN_FALLBACK = "Not reported"

# Placeholders that mean "not stated" in a design field (prompt v1.1+ emits
# DESIGN_FALLBACK; older null-style outputs are mapped to it here too).
_MISSING_DESIGN_VALUES = frozenset(
    {
        "",
        "null",
        "none",
        "n/a",
        "na",
        "unknown",
        "unspecified",
        "not reported",
        "not stated",
        "not specified",
        "not available",
        "not provided",
        "not mentioned",
        "unclear",
        "not applicable",
    }
)


def _norm_design_field(value: object) -> str:
    """Normalize a PICO field to displayable text, never null/blank.

    Missing, null, or placeholder values become DESIGN_FALLBACK so records
    always carry a structured, human-readable value instead of an empty one.
    """
    if value is None:
        return DESIGN_FALLBACK
    text = str(value).strip()
    if text.lower().rstrip(".") in _MISSING_DESIGN_VALUES:
        return DESIGN_FALLBACK
    return text or DESIGN_FALLBACK


def _fallback_design() -> StudyDesign:
    """Structured default design: every field honestly marked as unreported."""
    return StudyDesign(
        **{name: DESIGN_FALLBACK for name in StudyDesign.model_fields}
    )


async def extract_study_pico(title: str, abstract: str) -> StudyDesign:
    """Extract PICO design fields. Never raises; any failure yields a
    structured fallback design (all fields "Not reported") instead of an
    empty record, so stored studies always carry displayable PICO data."""
    if not is_llm_configured():
        logger.info("LLM unconfigured; returning fallback StudyDesign")
        return _fallback_design()
    try:
        prompt = load_prompt(STUDY_PROMPT_FILE)
        template = str(prompt["user_template"])
        # Literal .replace (not .format): template contains {{...}} literals.
        user = template.replace("{study_id_hint}", "auto").replace(
            "{paper_text}", _build_paper_text(title, abstract)
        )
        data = await _chat_json(str(prompt["system_prompt"]), user)
        # Prompt v1.1+ returns a {"design": {...}} object (strict JSON-object
        # mode rejects bare arrays); anything else is a contract violation.
        if isinstance(data, dict):
            design_data = data.get("design", {})
        else:
            logger.warning(
                "PICO response for %r was %s, not an object; using fallback",
                title[:60],
                type(data).__name__,
            )
            return _fallback_design()
        if not isinstance(design_data, dict):
            logger.warning(
                "PICO 'design' for %r was %s, not an object; using fallback",
                title[:60],
                type(design_data).__name__,
            )
            return _fallback_design()
        fields = {
            name: _norm_design_field(design_data.get(name))
            for name in StudyDesign.model_fields
        }
        return StudyDesign(**fields)
    except Exception as exc:  # noqa: BLE001 - extraction must never break search
        logger.warning("PICO extraction failed for %r: %s", title[:60], exc)
        return _fallback_design()


def _coerce_claim(item: object, study_id: str, index: int) -> Claim | None:
    if not isinstance(item, dict):
        return None
    text = str(item.get("text") or "").strip()
    if not text:
        return None
    direction = str(item.get("effect_direction") or "").strip().lower()
    try:
        confidence = float(item.get("confidence_score", 0.0))
    except (TypeError, ValueError):
        return None
    confidence = min(1.0, max(0.0, confidence))  # clamp, don't drop
    claim_id = str(item.get("claim_id") or "").strip() or f"{study_id}-c{index}"
    try:
        return Claim(
            claim_id=claim_id,
            study_id=study_id,  # enforce verbatim linkage, ignore LLM drift
            text=text,
            effect_direction=direction,  # type: ignore[arg-type]
            confidence_score=confidence,
            evidence_span=_norm_opt(item.get("evidence_span")),
        )
    except Exception as exc:  # noqa: BLE001 - skip invalid items, keep rest
        logger.warning("Skipping invalid claim %r: %s", claim_id, exc)
        return None


async def extract_study_claims(title: str, abstract: str, study_id: str) -> list[Claim]:
    """Extract atomic findings with EffectDirection. Returns [] on failure."""
    if not is_llm_configured():
        logger.info("LLM unconfigured; returning no claims for %s", study_id)
        return []
    try:
        prompt = load_prompt(CLAIMS_PROMPT_FILE)
        template = str(prompt["user_template"])
        user = template.replace("{study_id}", study_id).replace(
            "{paper_text}", _build_paper_text(title, abstract)
        )
        data = await _chat_json(str(prompt["system_prompt"]), user)
        # Prompt v1.1+ returns a {"claims": [...]} object (strict JSON-object
        # mode rejects bare arrays); older outputs may be a raw list.
        if isinstance(data, dict):
            items = data.get("claims", [])
        elif isinstance(data, list):
            items = data
        else:
            return []
        if not isinstance(items, list):
            return []
        claims = [
            claim
            for i, item in enumerate(items, start=1)
            if (claim := _coerce_claim(item, study_id, i)) is not None
        ]
        return claims
    except Exception as exc:  # noqa: BLE001 - extraction must never break search
        logger.warning("Claim extraction failed for %s: %s", study_id, exc)
        return []


async def extract_study_unified(
    title: str, abstract: str, study_id: str
) -> tuple[StudyDesign, list[Claim]]:
    """Extract PICO design + claims in a SINGLE LLM call. Never raises.

    Preferred entry point for search: one request per study instead of two,
    halving latency and free-tier quota burn. Each section degrades
    independently — a malformed design still keeps valid claims and vice
    versa; total failure yields ("Not reported" design, []).
    """
    if not is_llm_configured():
        logger.info("LLM unconfigured; returning fallback design, no claims")
        return _fallback_design(), []
    try:
        prompt = load_prompt(UNIFIED_PROMPT_FILE)
        template = str(prompt["user_template"])
        user = template.replace("{study_id}", study_id).replace(
            "{paper_text}", _build_paper_text(title, abstract)
        )
        data = await _chat_json(str(prompt["system_prompt"]), user)
        if not isinstance(data, dict):
            logger.warning(
                "Unified extraction for %s returned %s, not an object; using fallbacks",
                study_id,
                type(data).__name__,
            )
            return _fallback_design(), []
        design_data = data.get("design", {})
        if isinstance(design_data, dict):
            design = StudyDesign(
                **{
                    name: _norm_design_field(design_data.get(name))
                    for name in StudyDesign.model_fields
                }
            )
        else:
            logger.warning(
                "Unified 'design' for %s was %s; using fallback design",
                study_id,
                type(design_data).__name__,
            )
            design = _fallback_design()
        claims_data = data.get("claims", [])
        if isinstance(claims_data, list):
            claims = [
                claim
                for i, item in enumerate(claims_data, start=1)
                if (claim := _coerce_claim(item, study_id, i)) is not None
            ]
        else:
            logger.warning(
                "Unified 'claims' for %s was %s; using no claims",
                study_id,
                type(claims_data).__name__,
            )
            claims = []
        return design, claims
    except Exception as exc:  # noqa: BLE001 - extraction must never break search
        logger.warning("Unified extraction failed for %s: %s", study_id, exc)
        return _fallback_design(), []


__all__ = [
    "DESIGN_FALLBACK",
    "EXTRACTION_LOCK",
    "LLM_SEMAPHORE",
    "MAX_CONCURRENT_LLM_REQUESTS",
    "SEMAPHORE",
    "extract_study_claims",
    "extract_study_pico",
    "extract_study_unified",
    "is_llm_configured",
    "load_prompt",
]
