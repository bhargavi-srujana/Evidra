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
import hashlib
import itertools
import json
import logging
import re
import threading
import time
from functools import lru_cache
from pathlib import Path
from typing import Any

from openai import AsyncOpenAI, AuthenticationError, RateLimitError

from app.core.config import get_settings
from app.models.claim import Claim
from app.models.study import StudyDesign
from app.services.common import normalize_title

logger = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"
STUDY_PROMPT_FILE = "extract_study.json"
CLAIMS_PROMPT_FILE = "extract_claims.json"
UNIFIED_PROMPT_FILE = "extract_study_unified.json"
MAX_PAPER_WORDS = 2500
PLACEHOLDER_API_KEY = "sk-change-me"

# Concurrency guard: at most 4 LLM requests in flight at once, so a search
# payload fans out in parallel via asyncio.gather while the semaphore keeps
# bursts from tripping provider rate limits. This is the single choke point
# — every LLM call flows through _chat_json, so PICO, claim, topic-label,
# and contradiction-refinement calls are all covered even when callers
# dispatch with unbounded asyncio.gather.
MAX_CONCURRENT_LLM_REQUESTS = 4
LLM_SEMAPHORE = asyncio.Semaphore(MAX_CONCURRENT_LLM_REQUESTS)
# Back-compat alias matching the commonly suggested snippet shape.
SEMAPHORE = LLM_SEMAPHORE

# Rotation-layer guard: at most 4 concurrent LLM extractions in flight, so a
# burst of parallel studies with multiple API keys can spread across keys
# without spiking any single key into a 429. This bounds the key-rotation
# path in _do_chat_json; the burst cap above still applies when pacing is off.
EXTRACTION_SEMAPHORE = asyncio.Semaphore(4)

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
#     cap above (4 at a time) governs instead.
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

# --- API key rotation pool ---
# Cyclic iterator over settings.API_KEYS. Refreshed lazily by _next_api_key()
# whenever the configured keys change (tests mutate settings in place), so the
# module-level name always reflects current config. next() calls are guarded
# by _KEY_POOL_LOCK, making rotation safe across threads as well as asyncio
# tasks sharing the event loop.
_KEY_POOL_LOCK = threading.Lock()
_key_pool_snapshot: tuple[str, ...] = ()
key_pool: Any = itertools.cycle(())
_clients: dict[str, AsyncOpenAI] = {}


def _current_api_keys() -> list[str]:
    """Configured rotation keys, falling back to the legacy single key."""
    keys = [k for k in (get_settings().API_KEYS or []) if str(k).strip()]
    if not keys:
        legacy = (get_settings().OPENAI_API_KEY or "").strip()
        if legacy:
            keys = [legacy]
    return keys


def _next_api_key() -> str:
    """Next key from the rotating pool (thread-safe). Never returns blank.

    Raises:
        RuntimeError: no usable key is configured.
    """
    global key_pool, _key_pool_snapshot
    keys = _current_api_keys()
    if not keys:
        raise RuntimeError("LLM is not configured (no API keys in rotation pool)")
    with _KEY_POOL_LOCK:
        if tuple(keys) != _key_pool_snapshot:
            _key_pool_snapshot = tuple(keys)
            key_pool = itertools.cycle(keys)
        current_key = next(key_pool)
    return str(current_key)


def _pool_size() -> int:
    """Number of distinct keys currently in the rotation pool (0 if none)."""
    return len(_current_api_keys())


@lru_cache(maxsize=4)
def load_prompt(filename: str) -> dict[str, Any]:
    """Load (and cache) a versioned prompt definition from `app/prompts/`."""
    path = PROMPTS_DIR / filename
    return json.loads(path.read_text(encoding="utf-8"))


def is_llm_configured() -> bool:
    """True when at least one usable LLM key is in the rotation pool."""
    return bool(get_settings().API_KEYS)


def _get_client_for_key(api_key: str) -> AsyncOpenAI:
    """Cached async LLM client bound to one rotation-pool key."""
    key = (api_key or "").strip()
    client = _clients.get(key)
    if client is None:
        settings = get_settings()
        client = AsyncOpenAI(
            base_url=settings.OPENAI_BASE_URL,
            api_key=key,
            timeout=60.0,
            # No blind SDK retries: _chat_create() retries 429/503 itself
            # with quota-aware delays. Blind retries burn quota faster.
            max_retries=0,
        )
        _clients[key] = client
    return client


def _get_client() -> AsyncOpenAI | None:
    """Shared async LLM client, or None when unconfigured (no hard failure).

    Legacy entry point kept for backward compatibility; delegates to the
    rotation pool so multi-key setups are never bypassed.
    """
    if not is_llm_configured():
        return None
    try:
        return _get_client_for_key(_next_api_key())
    except RuntimeError:
        return None


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        lines = lines[1:]  # drop opening fence (``` or ```json)
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


def _extract_json_substring(text: str) -> str:
    """Recover JSON when the LLM adds leading/trailing commentary.

    Returns the span from the first `{` to the last `}` when both exist,
    else the input unchanged so `json.loads` raises normally.
    """
    start = text.find("{")
    end = text.rfind("}")
    if 0 <= start < end:
        return text[start : end + 1]
    return text


def _parse_llm_json(content: str) -> Any:
    """Parse LLM JSON output, tolerating fences and surrounding chatter."""
    cleaned = _strip_fences(content)
    try:
        return json.loads(cleaned)
    except (json.JSONDecodeError, ValueError):
        return json.loads(_extract_json_substring(cleaned))


def _norm_opt(value: object) -> str | None:
    """Normalize missing-value literals to None; strip everything else."""
    if value is None:
        return None
    text = str(value).strip()
    if text.lower().rstrip(".") in _NULL_LITERALS:
        return None
    return text or None


# Prompt-injection guard: untrusted spans (user-query entities, third-party
# paper text) travel inside <user_query> / <paper_content> delimiters per the
# prompt contracts. Strip delimiter lookalikes from the values before
# interpolation so a crafted query or poisoned snippet cannot break out of
# its span and masquerade as trusted instructions.
_TAG_BREAKOUT_RE = re.compile(r"</?(?:paper_content|user_query)\s*>", re.IGNORECASE)


def _sanitize_prompt_span(text: str, max_chars: int = 0) -> str:
    """Remove XML-delimiter lookalikes from untrusted prompt input."""
    cleaned = _TAG_BREAKOUT_RE.sub("", text or "").strip()
    if max_chars > 0:
        cleaned = cleaned[:max_chars]
    return cleaned


# Any recognized section heading: used to bound kept sections so trailing
# content (references, appendices, …) never leaks into them. Bare provider
# abstracts carry no headings and pass through untouched.
_HEADING_RE = re.compile(
    r"(?im)^[ \t]*(abstract|introductions?|background|methods?|methodology"
    r"|results?|findings?|discussions?|conclusions?|references?|bibliography"
    r"|acknowledgements?|appendix)[ \t]*:?[ \t]*$"
)


def _select_sections(text: str) -> str:
    """Keep only Abstract / Results (+Findings) / Conclusion sections.

    Full-text pastes are trimmed to the sections extraction actually needs;
    each kept section ends at the next heading of any kind, so references and
    appendices are dropped. Inputs without headings (the common
    provider-abstract case) return as-is.
    """
    parts = _HEADING_RE.split(text)
    if len(parts) < 3:
        return text
    sections: dict[str, str] = {}
    for i in range(1, len(parts), 2):
        name = parts[i].strip().lower()
        if name.startswith(("result", "finding")):
            key: str | None = "results"
        elif name.startswith("conclusion"):
            key = "conclusion"
        elif name.startswith("abstract"):
            key = "abstract"
        else:
            key = None
        if key is not None and key not in sections and i + 1 < len(parts):
            sections[key] = parts[i + 1].strip()
    if not sections:
        return text
    ordered = [
        f"{key.title()}: {sections[key]}"
        for key in ("abstract", "results", "conclusion")
        if key in sections
    ]
    return "\n\n".join(ordered)


def _truncate_words(text: str, max_words: int = MAX_PAPER_WORDS) -> str:
    """Hard word cap so inputs can never exhaust API token limits."""
    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words])


def _build_paper_text(title: str, abstract: str) -> str:
    body = _select_sections((abstract or "").strip())
    text = f"Title: {title.strip()}\nPaper text: {body}"
    return _truncate_words(text)


async def _build_rich_paper_text(
    title: str,
    abstract: str,
    serpapi_result: dict | None = None,
    prebuilt_rich: str | None = None,
) -> str:
    """High-character LLM payload, preferring SerpApi rich context.

    When `serpapi_result` is given, builds the payload via
    `get_rich_paper_context()` (Strategy 1 rich metadata + Strategy 2
    open-access PDF text) and applies the same section-selection + word cap.
    A caller-prefetched `prebuilt_rich` cascade payload is used as-is (no
    second PDF fetch). Falls back to the plain title/abstract payload when no
    result is given, the rich context is empty, or PDF enrichment fails.
    """
    if prebuilt_rich is not None:
        if prebuilt_rich.strip():
            return _truncate_words(_select_sections(prebuilt_rich.strip()))
        return _build_paper_text(title, abstract)
    if serpapi_result is not None:
        try:
            from app.services.search_serp import get_rich_paper_context

            rich = await get_rich_paper_context(serpapi_result)
            if isinstance(rich, str) and rich.strip():
                return _truncate_words(_select_sections(rich.strip()))
        except Exception as exc:  # noqa: BLE001 - enrichment never breaks extraction
            logger.warning("Rich paper context failed, using title/abstract: %s", exc)
    return _build_paper_text(title, abstract)


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


def _is_rate_limit_error(exc: Exception) -> bool:
    """True for rate-limit/quota exhaustion (429 class) specifically.

    Narrower than _is_retryable_llm_error: only 429s trigger key rotation /
    model failover. A 503 overload or contract error never switches keys.
    """
    if isinstance(exc, RateLimitError):
        return True
    text = str(exc).lower()
    if "response_format" in text:
        return False
    if getattr(exc, "status_code", None) == 429:
        return True
    return "429" in text or "rate limit" in text or "rate_limit" in text or "quota" in text


def _is_auth_error(exc: Exception) -> bool:
    """True for credential rejection (401 class): invalid/revoked API key.

    Unlike rate limits, this never resolves with retries — but rotation still
    tries the remaining pool keys (a later key may be valid) before giving up.
    """
    if isinstance(exc, AuthenticationError):
        return True
    if getattr(exc, "status_code", None) == 401:
        return True
    text = str(exc).lower()
    return (
        "invalid_api_key" in text
        or "invalid api key" in text
        or "incorrect api key" in text
        or "unauthorized" in text
        or ("authentication" in text and "error code: 401" in text)
    )


# Count of LLM credential rejections seen since process start. routes_search
# snapshots this around extraction: auth failures + zero extraction signal
# means "the key is bad", surfaced as an actionable 502 instead of silently
# returning hollow "Not reported" records with HTTP 200.
_AUTH_LOCK = threading.Lock()
AUTH_FAILURE_COUNT: int = 0


def record_auth_failure() -> None:
    """Thread-safe increment of the credential-rejection counter."""
    global AUTH_FAILURE_COUNT
    with _AUTH_LOCK:
        AUTH_FAILURE_COUNT += 1


async def _chat_create(
    client: Any, model: str, messages: list[dict[str, str]], use_json: bool
) -> Any:
    """One chat-completions call with quota-aware retries on 429/503.

    Up to 4 attempts per model (1 initial + LLM_MAX_RETRIES retries):
    429s honor the server's retry hint, otherwise exponential backoff
    (5s, 10s, 20s, … capped by LLM_MAX_RETRY_DELAY_SECONDS).
    """
    max_retries = max(0, int(get_settings().LLM_MAX_RETRIES))
    last_exc: Exception | None = None
    for attempt in range(1 + max_retries):
        try:
            kwargs: dict[str, Any] = {"model": model, "messages": messages, "temperature": 0}
            if use_json:
                kwargs["response_format"] = {"type": "json_object"}
            return await client.chat.completions.create(**kwargs)
        except Exception as exc:  # inspected for retryability
            last_exc = exc
            if attempt >= max_retries or not _is_retryable_llm_error(exc):
                raise
            delay = _retry_delay_for(exc, attempt)
            if delay is None:
                raise
            logger.warning(
                "LLM rate-limited on %s (%s); retry %d/%d in %.1fs",
                model,
                type(exc).__name__,
                attempt + 1,
                max_retries,
                delay,
            )
            await asyncio.sleep(delay)
    assert last_exc is not None  # unreachable; keeps type-checkers happy
    raise last_exc


async def _chat_create_with_fallback(
    client: Any, primary_model: str, messages: list[dict[str, str]], use_json: bool
) -> Any:
    """Chat completion with automatic failover on sustained rate limiting.

    The primary model gets its full retry budget first; if it is still
    rate-limited afterwards (e.g. daily-token exhaustion on
    openai/gpt-oss-120b), the configured OPENAI_FALLBACK_MODEL is tried with
    a fresh budget so extraction completes instead of failing the study.
    """
    try:
        return await _chat_create(client, primary_model, messages, use_json)
    except Exception as exc:
        if not _is_rate_limit_error(exc):
            raise
        fallback = (get_settings().OPENAI_FALLBACK_MODEL or "").strip()
        if not fallback or fallback == primary_model:
            raise
        logger.warning(
            "Primary model %s rate-limited after retries; failing over to %s",
            primary_model,
            fallback,
        )
        return await _chat_create(client, fallback, messages, use_json)


async def _create_with_plain_retry(
    client: Any, model: str, messages: list[dict[str, str]], *, with_failover: bool
) -> Any:
    """One attempt with plain-JSON retry when the gateway rejects response_format."""
    try:
        if with_failover:
            return await _chat_create_with_fallback(client, model, messages, use_json=True)
        return await _chat_create(client, model, messages, use_json=True)
    except Exception as exc:
        # Some OpenAI-compatible gateways reject response_format; retry plain.
        if "response_format" not in str(exc).lower():
            raise
        logger.info("LLM gateway rejected response_format; retrying without it")
        if with_failover:
            return await _chat_create_with_fallback(client, model, messages, use_json=False)
        return await _chat_create(client, model, messages, use_json=False)


async def _do_chat_json(system_prompt: str, user_prompt: str) -> Any:
    """Single chat completion parsed as JSON. Raises on transport/parse failure.

    Key rotation (capped at 3 concurrent extractions via EXTRACTION_SEMAPHORE):
    the first attempt runs the primary model on the next pooled key with the
    full retry + model-failover budget. Each RateLimitError / HTTP 429 rotates
    to the next key (`current_key = next(key_pool)`) and retries on the
    lighter fallback model (OPENAI_FALLBACK_MODEL, default
    llama-3.1-8b-instant). Credential rejections (401) are recorded and also
    rotate (fail-fast, no sleep). Non-rate-limit errors propagate immediately.
    When every key is exhausted the last error propagates, and the extractors
    degrade to the structured title/snippet fallback (never an unhandled
    exception at the search layer).
    """
    settings = get_settings()
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    pool_size = _pool_size()
    if pool_size == 0:
        raise RuntimeError("LLM is not configured (no API keys in rotation pool)")
    fallback_model = (settings.OPENAI_FALLBACK_MODEL or "").strip() or "llama-3.1-8b-instant"
    last_exc: Exception | None = None
    async with EXTRACTION_SEMAPHORE:
        for rotate_no in range(pool_size):
            current_key = _next_api_key()
            client = _get_client_for_key(current_key)
            if rotate_no == 0:
                model, with_failover = settings.OPENAI_MODEL, True
            else:
                model, with_failover = fallback_model, False
            try:
                response = await _create_with_plain_retry(
                    client, model, messages, with_failover=with_failover
                )
            except Exception as exc:  # inspected for rotation
                if _is_auth_error(exc):
                    # Bad/revoked key: fail fast on this key (no sleep), record
                    # it, and rotate — a later pool key may still be valid.
                    record_auth_failure()
                    last_exc = exc
                    logger.warning(
                        "LLM rotation %d/%d rejected credentials on %s (%s); trying next key",
                        rotate_no + 1,
                        pool_size,
                        model,
                        type(exc).__name__,
                    )
                    continue
                if not _is_rate_limit_error(exc):
                    raise
                last_exc = exc
                logger.warning(
                    "LLM rotation %d/%d rate-limited on %s (%s); trying next key with %s",
                    rotate_no + 1,
                    pool_size,
                    model,
                    type(exc).__name__,
                    fallback_model,
                )
                continue
            content = (response.choices[0].message.content or "").strip()
            if not content:
                raise ValueError("LLM returned empty content")
            return _parse_llm_json(content)
    assert last_exc is not None  # unreachable when pool_size >= 1; keeps type-checkers happy
    raise last_exc


async def _chat_json(system_prompt: str, user_prompt: str) -> Any:
    """Chat completion parsed as JSON. Raises on transport/parse failure.

    Guarded twice: free-tier pacing (EXTRACTION_LOCK + minimum interval
    between starts, default 12s for 5 RPM providers) keeps 10-15 parallel
    study extractions from tripping 429s; transient 429/503s get up to 4
    attempts per model honoring the server's retry hint, then fail over to
    OPENAI_FALLBACK_MODEL on sustained rate limiting; with pacing disabled
    the LLM_SEMAPHORE burst cap (MAX_CONCURRENT_LLM_REQUESTS) applies instead.
    The pacing gap is pool-aware (configured interval / rotation-pool size):
    rotation spreads starts across keys, so each key still sees roughly the
    configured gap while multi-key setups stop paying the full serial cost.
    Underneath, _do_chat_json rotates across the API_KEYS pool (at most 3
    concurrent rotations via EXTRACTION_SEMAPHORE), retrying rate-limited
    keys on the lighter fallback model before degrading gracefully.
    """
    global _last_llm_start
    interval = _throttle_interval()
    if interval > 0:
        # Per-key protection with a shared global lock: divide by the pool
        # size (round-robin rotation approximates even spread). Single key
        # setups are unchanged; 3 keys turn a 12s global gap into ~4s.
        pool_size = max(1, _pool_size())
        interval = interval / pool_size
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
    return StudyDesign(**{name: DESIGN_FALLBACK for name in StudyDesign.model_fields})


async def extract_study_pico(
    title: str,
    abstract: str,
    serpapi_result: dict | None = None,
    rich_context: str | None = None,
) -> StudyDesign:
    """Extract PICO design fields. Never raises; any failure yields a
    structured fallback design (all fields "Not reported") instead of an
    empty record, so stored studies always carry displayable PICO data.

    When `serpapi_result` (a raw SerpApi organic result) is provided, the
    LLM payload is built via `get_rich_paper_context()` — rich metadata
    (title + publication summary + snippet) plus open-access PDF text —
    so the model can infer PICO details logically from the extended
    context instead of defaulting to "Not reported". A caller-prefetched
    `rich_context` cascade payload is reused as-is (no second PDF fetch).
    """
    if not is_llm_configured():
        logger.info("LLM unconfigured; returning fallback StudyDesign")
        return _fallback_design()
    try:
        prompt = load_prompt(STUDY_PROMPT_FILE)
        template = str(prompt["user_template"])
        paper_text = await _build_rich_paper_text(
            title, abstract, serpapi_result, prebuilt_rich=rich_context
        )
        # Literal .replace (not .format): template contains {{...}} literals.
        # paper_text is third-party controlled: sanitize delimiter lookalikes
        # so it cannot break out of its <paper_content> span.
        user = template.replace("{study_id_hint}", "auto").replace(
            "{paper_text}", _sanitize_prompt_span(paper_text)
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
            name: _norm_design_field(design_data.get(name)) for name in StudyDesign.model_fields
        }
        return StudyDesign(**fields)
    except Exception as exc:  # noqa: BLE001 - extraction must never break search
        logger.warning("PICO extraction failed for %r: %s", title[:60], exc)
        return _fallback_design()


async def extract_pico_from_study(
    serpapi_result: dict | None = None,
    title: str = "",
    abstract: str = "",
) -> StudyDesign:
    """Strategy 1 + 2 PICO entry point: rich SerpApi context straight to the LLM.

    Awaits `get_rich_paper_context(serpapi_result)` first to run the
    Strategy 2 (PDF) -> Strategy 1 (metadata) cascade, then injects the
    resulting payload into the `<paper_content>` prompt block via
    `extract_study_pico` (prefetched, so the PDF is fetched exactly once).
    `title`/`abstract` are used directly when no `serpapi_result` is given
    (or to fill gaps when the result lacks them). Never raises; failures
    yield the "Not reported" fallback design.
    """
    resolved_title = title.strip()
    resolved_abstract = abstract.strip()
    rich_context: str | None = None
    if serpapi_result is not None and isinstance(serpapi_result, dict):
        resolved_title = resolved_title or str(serpapi_result.get("title") or "").strip()
        if not resolved_abstract:
            snippet = str(serpapi_result.get("snippet") or "").strip()
            pub = serpapi_result.get("publication_info") or {}
            summary = str(pub.get("summary") or "").strip() if isinstance(pub, dict) else ""
            resolved_abstract = snippet or summary
        try:
            from app.services.search_serp import get_rich_paper_context

            rich_context = await get_rich_paper_context(serpapi_result)
        except Exception as exc:  # noqa: BLE001 - cascade failure falls back below
            logger.warning("Rich paper context failed, using title/abstract: %s", exc)
            rich_context = None
    return await extract_study_pico(
        resolved_title, resolved_abstract, serpapi_result, rich_context=rich_context
    )


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
    # Strict grounding fields: core finding + exact supporting quote. A
    # verbatim quote backs up evidence_span when the latter is absent, so
    # every claim keeps a quotable span whenever the text provides one.
    conclusion = _norm_conclusion(item.get("conclusion"))
    verbatim_quote = _norm_opt(item.get("verbatim_evidence_quote"))
    evidence = _norm_opt(item.get("evidence_span")) or verbatim_quote
    try:
        return Claim(
            claim_id=claim_id,
            study_id=study_id,  # enforce verbatim linkage, ignore LLM drift
            text=text,
            effect_direction=direction,  # type: ignore[arg-type]
            confidence_score=confidence,
            evidence_span=evidence,
            conclusion=conclusion,
            verbatim_evidence_quote=verbatim_quote,
        )
    except Exception as exc:  # noqa: BLE001 - skip invalid items, keep rest
        logger.warning("Skipping invalid claim %r: %s", claim_id, exc)
        return None


async def extract_study_claims(
    title: str,
    abstract: str,
    study_id: str,
    serpapi_result: dict | None = None,
) -> list[Claim]:
    """Extract atomic findings with EffectDirection. Returns [] on failure."""
    if not is_llm_configured():
        logger.info("LLM unconfigured; returning no claims for %s", study_id)
        return []
    try:
        prompt = load_prompt(CLAIMS_PROMPT_FILE)
        template = str(prompt["user_template"])
        paper_text = await _build_rich_paper_text(title, abstract, serpapi_result)
        user = template.replace("{study_id}", study_id).replace(
            "{paper_text}", _sanitize_prompt_span(paper_text)
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


def make_study_id(
    title: str, year: int | None = None, doi: str | None = None
) -> str:
    """Deterministic, position-independent study ID.

    Uses `sha256(clean DOI)` when a usable DOI exists, else
    `sha256(normalized_title|year)` — so the same paper retrieved in a
    different order, page, or query maps to one stable ID (no duplicate
    Study docs or orphaned claim links). Never raises.
    """
    clean_doi = (doi or "").strip().lower().rstrip(".,;").strip()
    if clean_doi:
        digest = hashlib.sha256(clean_doi.encode()).hexdigest()
    else:
        try:
            norm = normalize_title(title or "")
        except Exception:  # noqa: BLE001 - never fail ID generation
            norm = (title or "").strip().lower()
        digest = hashlib.sha256(f"{norm}|{year or ''}".encode()).hexdigest()
    return f"study-{digest[:12]}"


# --- Strict factual extraction (grounding) contract ---
# Verbatim evidence engine rules enforced on every unified extraction call:
# the LLM may only report what is explicitly stated inside <paper_content>,
# never infer conclusions from titles/snippets, and must ground each claim
# in an exact quote.
STRICT_GROUNDING_SYSTEM_PROMPT = (
    "You are a verbatim evidence extraction engine for academic papers."
    " Analyze ONLY the provided text inside <paper_content> tags."
    " NEVER guess, judge, or infer study conclusions or PICO parameters from paper titles or snippets alone."
    " If the provided text does not contain explicit findings or a conclusion, set 'conclusion' to 'Unspecified in provided text'."
)

# Title-inference guard: a suggestive title is a topic label, not a result.
TITLE_INFERENCE_GUARD = "DO NOT assume a positive or negative finding simply because the paper title asks a question or suggests a relationship (e.g. 'Does X cause Y?'). Base the conclusion strictly on explicit results reported in the text."

# Fallback markers for the grounded claim schema below.
CONCLUSION_UNSPECIFIED = "Unspecified in provided text"
FIELD_UNSPECIFIED = "Unspecified in text"

# Expected per-claim JSON schema: every claim carries PICO grounding plus a
# directly-extracted core finding and its exact supporting quote.
GROUNDED_CLAIM_SCHEMA = """{
  "effect_direction": "Positive" | "Negative" | "Conditional" | "No Effect" | "Unspecified",
  "population": "<target group or 'Unspecified in text'>",
  "intervention": "<treatment or 'Unspecified in text'>",
  "control": "<baseline or 'Unspecified in text'>",
  "outcome": "<metric or 'Unspecified in text'>",
  "conclusion": "<1-2 sentence core finding extracted directly from abstract/text>",
  "verbatim_evidence_quote": "<exact quote from the provided text supporting the conclusion>"
}"""

# Appended to the unified user prompt so each returned claim object carries
# the grounding fields above (conclusion + verbatim quote).
GROUNDING_CLAIM_FIELDS_BLOCK = (
    "\n\nGROUNDING — STRICT FACTUAL EXTRACTION. Every claim object must also "
    "include exactly these two additional keys:\n"
    '- "conclusion": 1-2 sentence core finding extracted directly from the '
    "abstract/text. If the provided text contains no explicit findings, set "
    "'conclusion' to 'Unspecified in provided text'.\n"
    '- "verbatim_evidence_quote": exact quote from the provided text '
    "supporting the conclusion (empty string when no supporting span exists). "
    "Never paraphrase this quote.\n"
    "PICO grounding per claim: report population, intervention, control, and "
    "outcome strictly as stated in the text, using 'Unspecified in text' for "
    "any element the text does not state. " + TITLE_INFERENCE_GUARD
)


def _grounded_system_prompt(base_system_prompt: str) -> str:
    """Layer strict verbatim-grounding rules onto the stored system prompt.

    Idempotent: when the stored prompt already carries the grounding contract
    (e.g. prompt file updated in place), it is returned unchanged instead of
    duplicating the instructions.
    """
    base = (base_system_prompt or "").strip()
    if "verbatim evidence extraction engine" in base:
        return base
    return f"{base}\n\n{STRICT_GROUNDING_SYSTEM_PROMPT}\n\n{TITLE_INFERENCE_GUARD}"


def _norm_conclusion(value: object) -> str:
    """Normalize the grounded conclusion field, never blank.

    Missing or empty conclusions honestly read as 'Unspecified in provided
    text' so downstream consumers can distinguish grounded findings from
    absent ones instead of receiving an empty string.
    """
    if value is None:
        return CONCLUSION_UNSPECIFIED
    text = str(value).strip()
    return text or CONCLUSION_UNSPECIFIED


def _backstop_claim(title: str, abstract: str, study_id: str) -> list[Claim]:
    """One honest unclear claim so a paper never vanishes from the corpus.

    Used ONLY on the success path when the LLM returns a valid response with
    zero usable claims (thin snippets, unparseable items). Direction is
    unclear at low confidence (0.3, the heuristic scale); the evidence span
    is the leading verbatim words of the snippet/title and the conclusion is
    the leading sentence(s) — or 'Unspecified in provided text' when even
    that is absent. Never invents findings; flags the paper as unstated
    instead of dropping it.
    """
    source = (abstract or "").strip() or (title or "").strip()
    if not source:
        return []
    words = source.split()
    span = " ".join(words[:60]).strip()
    # Conclusions come from body text only: a title alone is a topic label,
    # never a finding, so title-only papers honestly read as unspecified.
    body = (abstract or "").strip()
    sentences = re.split(r"(?<=[.!?])\s+", body) if body else []
    conclusion = " ".join(s for s in sentences[:2] if s.strip()).strip()[:500]
    try:
        return [
            Claim(
                claim_id=f"{study_id}-c1",
                study_id=study_id,
                text=" ".join(words[:40]).strip() or source[:200],
                effect_direction="unclear",  # type: ignore[arg-type]
                confidence_score=_FALLBACK_CONFIDENCE,
                evidence_span=span or None,
                conclusion=conclusion or CONCLUSION_UNSPECIFIED,
                verbatim_evidence_quote=span or None,
            )
        ]
    except Exception:  # noqa: BLE001 - backstop must never break extraction
        logger.warning("Backstop claim failed for %s", study_id)
        return []


async def _extract_study_unified_inner(
    title: str,
    abstract: str,
    study_id: str,
    intervention: str = "",
    outcome: str = "",
    serpapi_result: dict | None = None,
    anchor_question: str = "",
) -> tuple[StudyDesign, list[Claim], bool, bool]:
    """Unified extraction with explicit fallback + auth provenance flags.

    Returns `(design, claims, fallback, auth_failed)`:
    - `fallback` True when the result came from a heuristic/blank fallback
      (LLM unconfigured, contract violation, quota-exhausted heuristic, or
      zero-claim backstop) instead of the LLM. Callers mark the Study
      `is_fallback=True` so fallback records are served but never frozen
      into search_cache.
    - `auth_failed` True when this paper saw a credential rejection (401).
      Unlike the old process-global counter snapshot, this is per-paper so
      concurrent searches cannot misattribute another search's failure.
    """
    if not is_llm_configured():
        logger.info("LLM unconfigured; returning fallback design, no claims")
        return _fallback_design(), [], True, False
    try:
        prompt = load_prompt(UNIFIED_PROMPT_FILE)
        template = str(prompt["user_template"])
        paper_text = await _build_rich_paper_text(title, abstract, serpapi_result)
        # intervention/outcome are raw user-query substrings and paper_text is
        # third-party controlled: strip delimiter lookalikes (and cap entity
        # length) so neither can break out of its <user_query>/<paper_content>
        # span and masquerade as trusted instructions.
        anchor = _sanitize_prompt_span(anchor_question.strip(), 300)
        if anchor:
            # Natural question form ("Do men sleep more than women?") reads
            # better than the templated "Does X increase Y?" form, which is
            # ungrammatical for group comparisons. The polarity rules below
            # still resolve verdicts against {intervention}/{outcome}.
            template = template.replace(
                "Does {intervention} increase {outcome}?", anchor, 1
            )
        user = (
            template.replace("{study_id}", study_id)
            .replace(
                "{intervention}",
                _sanitize_prompt_span(
                    intervention.strip() or "the studied intervention", 200
                ),
            )
            .replace(
                "{outcome}",
                _sanitize_prompt_span(outcome.strip() or "the studied outcome", 200),
            )
            .replace("{paper_text}", _sanitize_prompt_span(paper_text))
        )
        # Strict factual grounding: require per-claim conclusion + verbatim
        # quote (idempotent when the stored template already carries it).
        if "verbatim_evidence_quote" not in template:
            user = f"{user}{GROUNDING_CLAIM_FIELDS_BLOCK}"
        system_prompt = _grounded_system_prompt(str(prompt["system_prompt"]))
        data = await _chat_json(system_prompt, user)
        if not isinstance(data, dict):
            logger.warning(
                "Unified extraction for %s returned %s, not an object; using fallbacks",
                study_id,
                type(data).__name__,
            )
            return _fallback_design(), [], True, False
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
        used_backstop = False
        if isinstance(claims_data, list):
            claims = [
                claim
                for i, item in enumerate(claims_data, start=1)
                if (claim := _coerce_claim(item, study_id, i)) is not None
            ]
            if not claims:
                # Valid LLM response but nothing usable: backstop with one
                # honest unclear claim so this paper still contributes a
                # snippet-grounded conclusion instead of vanishing.
                # Flagged as fallback so it is served but never cached.
                logger.info(
                    "Unified extraction returned no usable claims for %s; using backstop",
                    study_id,
                )
                claims = _backstop_claim(title, abstract, study_id)
                used_backstop = True
        else:
            logger.warning(
                "Unified 'claims' for %s was %s; using no claims",
                study_id,
                type(claims_data).__name__,
            )
            claims = []
        return design, claims, used_backstop, False
    except Exception as exc:  # noqa: BLE001 - extraction must never break search
        logger.warning("Unified extraction failed for %s: %s", study_id, exc)
        if _is_auth_error(exc):
            # Credential rejection survived rotation over every pool key.
            logger.warning("LLM auth failed for %s; heuristic fallback", study_id)
            design, claims = extract_study_fallback(
                title, abstract, study_id, intervention, outcome
            )
            return design, claims, True, True
        if _is_retryable_llm_error(exc):
            # Quota/overload survived retries + failover: squeeze signal from
            # metadata with zero further API cost instead of a blank record.
            logger.info("LLM unavailable; title/snippet heuristic fallback for %s", study_id)
            design, claims = extract_study_fallback(
                title, abstract, study_id, intervention, outcome
            )
            return design, claims, True, False
        return _fallback_design(), [], True, False


async def extract_study_unified(
    title: str,
    abstract: str,
    study_id: str,
    intervention: str = "",
    outcome: str = "",
    serpapi_result: dict | None = None,
    anchor_question: str = "",
) -> tuple[StudyDesign, list[Claim]]:
    """Extract PICO design + claims in a SINGLE LLM call. Never raises.

    Preferred entry point for search: one request per study instead of two,
    halving latency and free-tier quota burn. ``intervention``/``outcome``
    (from query normalization) anchor the prompt's direction-polarity rules so
    effect directions are judged against the tested question, not sentiment
    words. Each section degrades independently — a malformed design still keeps
    valid claims and vice versa; total failure yields ("Not reported" design,
    []).

    When ``serpapi_result`` is provided, the payload is built via
    `get_rich_paper_context()` (rich metadata + PDF text) so PICO fields can
    be inferred logically from the extended context.
    """
    design, claims, _fallback, _auth = await _extract_study_unified_inner(
        title, abstract, study_id, intervention, outcome, serpapi_result, anchor_question
    )
    return design, claims


# --- Deterministic title/snippet fallback (zero LLM calls) ---

_NO_EFFECT_CUES = (
    "no significant",
    "not significant",
    "no effect",
    "did not",
    "does not",
    "do not",
    "not associated",
    "no association",
    "no difference",
    "null result",
    "failed to",
)
_CONDITIONAL_CUES = (
    "depends on",
    "moderated by",
    "only when",
    "under certain conditions",
    "conditional on",
    "context-dependent",
)
_POSITIVE_CUES = (
    "improv",
    "increas",
    "enhanc",
    "benefit",
    "better",
    "higher",
    "greater",
    "boost",
    "effective",
    "positive",
    "gain",
)
_NEGATIVE_CUES = (
    "decreas",
    "reduc",
    "reduct",
    "declin",
    "impair",
    "worse",
    "lower",
    "deficit",
    "harm",
    "negative",
    "detrimental",
    "disrupt",
)
_WITHIN_SUBJECT_CUES = (
    "within-subject",
    "within subject",
    "crossover",
    "cross-over",
    "pre-post",
    "pre post",
    "self-controlled",
)
# Ordered specific -> general; first substring hit wins.
_POPULATION_CUES: tuple[tuple[str, str], ...] = (
    ("undergrad", "College students"),
    ("college", "College students"),
    ("high school", "High school students"),
    ("pupil", "School pupils"),
    ("student", "Students"),
    ("older adult", "Older adults"),
    ("elderly", "Older adults"),
    ("adolescent", "Adolescents"),
    ("teenager", "Adolescents"),
    ("child", "Children"),
    ("infant", "Infants"),
    ("patient", "Patients"),
    ("mice", "Mice"),
    ("mouse", "Mice"),
    ("rat", "Rats"),
    ("primate", "Primates"),
    ("monkey", "Monkeys"),
    ("women", "Women"),
    ("men", "Men"),
    ("adult", "Adults"),
)
_SAMPLE_RE = re.compile(
    r"\b[Nn]\s*=\s*(\d[\d,]*)\b|\b(\d[\d,]*)\s+"
    r"(participants|subjects|students|patients|volunteers|adults|children)\b"
)
_FALLBACK_CONFIDENCE = 0.3


def _heuristic_direction(text: str) -> str:
    """Direction guess from title/snippet cue words (no LLM)."""
    lowered = text.lower()
    if any(cue in lowered for cue in _NO_EFFECT_CUES):
        return "no_effect"
    if any(cue in lowered for cue in _CONDITIONAL_CUES):
        return "conditional"
    positive = sum(lowered.count(cue) for cue in _POSITIVE_CUES)
    negative = sum(lowered.count(cue) for cue in _NEGATIVE_CUES)
    if positive > negative:
        return "increases"
    if negative > positive:
        return "decreases"
    return "unclear"


def _heuristic_sample_size(text: str) -> str | None:
    """Participant count like 'N=120' / '24 participants', else None."""
    match = _SAMPLE_RE.search(text)
    if not match:
        return None
    if match.group(1):
        return f"N={match.group(1)}"
    return f"{match.group(2)} {match.group(3)}"


def _heuristic_population(text: str) -> str | None:
    """Group label from explicit descriptors, else None (never invented)."""
    lowered = text.lower()
    for cue, label in _POPULATION_CUES:
        if cue in lowered:
            return label
    return None


def extract_study_fallback(
    title: str,
    abstract: str,
    study_id: str,
    intervention: str = "",
    outcome: str = "",
) -> tuple[StudyDesign, list[Claim]]:
    """Classify direction + PICO from title/snippet only. Never raises, never
    calls the LLM: safe to use when quota is exhausted. Everything returned is
    verbatim metadata or an explicit heuristic at low confidence (0.3), so it
    can never outrank real extractions downstream."""
    text = f"{title or ''} {abstract or ''}".strip()
    lowered = text.lower()
    # Direction cues are read from the abstract/snippet ONLY — never from the
    # title. Title sentiment ("impair", "negative", ...) describes a topic,
    # not the paper's finding; judging a conclusion from it mislabels studies.
    # With no abstract text the honest verdict is "unclear", not a title guess.
    evidence_text = (abstract or "").strip()
    direction = _heuristic_direction(evidence_text) if evidence_text else "unclear"
    design = StudyDesign(
        population=_heuristic_population(text) or DESIGN_FALLBACK,
        sample_size=_heuristic_sample_size(text) or DESIGN_FALLBACK,
        intervention=(intervention or "").strip() or DESIGN_FALLBACK,
        control=(
            "Self-controlled / Baseline"
            if any(cue in lowered for cue in _WITHIN_SUBJECT_CUES)
            else DESIGN_FALLBACK
        ),
        task_type=DESIGN_FALLBACK,
        measurement_metric=(outcome or "").strip() or DESIGN_FALLBACK,
        study_duration=DESIGN_FALLBACK,
        study_type=DESIGN_FALLBACK,
    )
    span = " ".join((abstract or title or "").split()[:60]).strip()
    claims: list[Claim] = []
    if span:
        try:
            claims = [
                Claim(
                    claim_id=f"{study_id}-c1",
                    study_id=study_id,
                    text=(title or "").strip() or span,
                    effect_direction=direction,  # type: ignore[arg-type]
                    confidence_score=_FALLBACK_CONFIDENCE,
                    evidence_span=span,
                )
            ]
        except Exception:  # noqa: BLE001 - malformed metadata yields no claims
            claims = []
    return design, claims


__all__ = [
    "AUTH_FAILURE_COUNT",
    "DESIGN_FALLBACK",
    "EXTRACTION_LOCK",
    "EXTRACTION_SEMAPHORE",
    "LLM_SEMAPHORE",
    "MAX_CONCURRENT_LLM_REQUESTS",
    "SEMAPHORE",
    "extract_pico_from_study",
    "extract_study_claims",
    "extract_study_fallback",
    "extract_study_pico",
    "extract_study_unified",
    "is_llm_configured",
    "key_pool",
    "load_prompt",
    "make_study_id",
    "record_auth_failure",
]
