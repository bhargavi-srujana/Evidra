"""POST /api/v1/search — live literature search + structured extraction.

Pipeline:
  1. Normalize the natural-language query (neutral provider terms +
     intervention/outcome entities for direction anchoring).
  2. Check the MongoDB `search_cache` for this neutral query (instant hit).
  3. Retrieve papers via SerpApi Scholar, with Semantic Scholar fallback
     (also used to backfill truncated/missing SerpApi abstracts).
  4. Run unified single-call PICO+claim extraction concurrently (bounded semaphore).
  5. Best-effort upsert of Study/Claim docs plus the aggregated `search_cache`
     entry into MongoDB.
  6. Return validated `Study` + `Claim` arrays (persistence never 500s).
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from app.core.rate_limit import limiter
from app.db.mongo import get_db
from app.models.claim import Claim
from app.models.study import Author, Study, StudyDesign
from app.services import extraction as extraction_svc
from app.services.common import (
    RawPaper,
    SearchProviderError,
    decompose_query,
    normalize_title,
)
from app.services.extraction import (
    DESIGN_FALLBACK,
    _extract_study_unified_inner,
    _fallback_design,
    make_study_id,
)
from app.services.query_parser import parse_query
from app.services.search_s2 import search_semantic_scholar
from app.services.search_serp import is_serpapi_configured, search_google_scholar

logger = logging.getLogger(__name__)

router = APIRouter(tags=["search"])

MAX_CONCURRENT_EXTRACTIONS = 4
SERPAPI_PAGE_CAP = 20

# Repeat-query cache: aggregated search responses keyed by normalized neutral
# query, so identical searches return in milliseconds with zero LLM calls.
SEARCH_CACHE_COLLECTION = "search_cache"
SEARCH_CACHE_TTL_SECONDS = 7 * 24 * 3600  # 7 days


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    query: str = Field(min_length=1)
    max_results: int = Field(default=6, ge=1, le=50)


class SearchResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str
    results: list[Study]
    claims: list[Claim] = Field(default_factory=list)


def _needs_enrichment(papers: list[RawPaper]) -> bool:
    """True when any SerpApi record lacks a usable abstract."""
    return any(p.abstract_missing() for p in papers)


def _dedupe_papers(papers: list[RawPaper]) -> list[RawPaper]:
    seen: set[str] = set()
    unique: list[RawPaper] = []
    for paper in papers:
        key = normalize_title(paper.title)
        if key and key not in seen:
            seen.add(key)
            unique.append(paper)
    return unique


def _merge_papers(primary: list[RawPaper], fallback: list[RawPaper], limit: int) -> list[RawPaper]:
    """Backfill missing SerpApi abstracts from S2, then top up with S2-only hits."""
    by_title = {normalize_title(p.title): p for p in primary}
    extras: list[RawPaper] = []
    for paper in fallback:
        key = normalize_title(paper.title)
        existing = by_title.get(key)
        if existing is not None:
            if existing.abstract_missing() and not paper.abstract_missing():
                existing.snippet = paper.snippet
                if existing.year is None:
                    existing.year = paper.year
                if existing.venue is None:
                    existing.venue = paper.venue
                if existing.doi is None:
                    existing.doi = paper.doi
                if existing.link is None:
                    existing.link = paper.link
        elif key:
            extras.append(paper)
    return _dedupe_papers([*primary, *extras])[:limit]


def _make_study_id(
    title: str, year: int | None = None, doi: str | None = None
) -> str:
    """Position-independent stable ID (legacy wrapper).

    Delegates to `extraction.make_study_id` (sha256 of clean DOI, else
    sha256 of normalized title + year) so reordered/repeated retrievals map
    to one ID. The old `sha1(title|year|index)` form is gone: the positional
    index fragmented the store with duplicates per result order.
    """
    return make_study_id(title, year, doi)


def _search_cache_key(neutral_query: str) -> str:
    """Stable cache key: normalized neutral query, case/whitespace-insensitive."""
    normalized = " ".join((neutral_query or "").strip().lower().split())
    digest = hashlib.sha1(normalized.encode()).hexdigest()
    return f"search-{digest[:16]}"


# Minimum claim confidence that counts as cacheable signal. Heuristic
# title/snippet fallback claims sit at _FALLBACK_CONFIDENCE (0.3) precisely so
# they never freeze a low-quality answer into the 7-day cache.
_CACHEABLE_CONFIDENCE = 0.5


# Design values that carry no extraction signal (never count toward cacheability).
_NON_SIGNAL_DESIGN_VALUES = frozenset(
    {
        "",
        "not reported",
        "fallback",
        "null",
        "none",
        "n/a",
        "na",
        "unknown",
        "unclear",
    }
)


def _design_values(design: object) -> list[object] | None:
    """Raw design field values, or None when the design is missing."""
    if design is None:
        return None
    if isinstance(design, str):
        return [design]
    if isinstance(design, dict):
        return list(design.values())
    if hasattr(design, "model_dump"):
        try:
            return list(design.model_dump().values())  # type: ignore[union-attr]
        except Exception:  # noqa: BLE001 - corrupt design reads as missing
            return None
    return None


def _is_cacheable(studies: list[Study], claims: list[Claim]) -> bool:
    """True when the response carries real extraction signal.

    Cacheable = any genuine design field, or any claim at/above
    _CACHEABLE_CONFIDENCE. Rejected (False) when any study is marked
    `is_fallback`, when a study design is missing, or when a design is the
    bare "fallback" placeholder — so quota-exhausted heuristic runs are
    never frozen into the 7-day cache and a later retry re-extracts instead
    of serving the failure for TTL days.
    """
    for study in studies:
        data = (
            study.model_dump()
            if isinstance(study, Study)
            else (study if isinstance(study, dict) else {})
        )
        if data.get("is_fallback") is True:
            return False
        design = data.get("design", data.get("study_design"))
        values = _design_values(design)
        if values is None:
            return False
        if (
            len(values) == 1
            and isinstance(values[0], str)
            and values[0].strip().lower() == "fallback"
        ):
            return False
    fallback = DESIGN_FALLBACK.strip().lower()
    for study in studies:
        data = (
            study.model_dump()
            if isinstance(study, Study)
            else (study if isinstance(study, dict) else {})
        )
        for value in _design_values(data.get("design", data.get("study_design"))) or []:
            if (
                isinstance(value, str)
                and value.strip()
                and value.strip().lower() != fallback
                and value.strip().lower() not in _NON_SIGNAL_DESIGN_VALUES
            ):
                return True
    return any(claim.confidence_score >= _CACHEABLE_CONFIDENCE for claim in claims)


def _coerce_cached_response(doc: dict, query: str, max_results: int) -> SearchResponse | None:
    """Rebuild a SearchResponse from a cache doc; None when invalid/empty.

    Slices to the requested max_results and drops claims whose studies were
    sliced away, so smaller repeat requests stay consistent. Entries holding
    heuristic-fallback studies read as a miss so stale low-quality answers
    are re-extracted instead of served.
    """
    try:
        studies = [Study(**item) for item in doc.get("results", [])]
        claims = [Claim(**item) for item in doc.get("claims", [])]
    except Exception:  # noqa: BLE001 - corrupt cache entry reads as a miss
        return None
    if not studies:
        return None
    if any(study.is_fallback for study in studies):
        return None
    studies = studies[:max_results]
    keep_ids = {study.study_id for study in studies}
    claims = [claim for claim in claims if claim.study_id in keep_ids]
    return SearchResponse(query=query, results=studies, claims=claims)


async def _cache_lookup(key: str) -> dict | None:
    """Fetch a fresh cache doc by key; None on miss, expiry, or store outage."""
    try:
        doc = await get_db()[SEARCH_CACHE_COLLECTION].find_one({"key": key})
    except Exception as exc:  # noqa: BLE001 - cache must never break search
        logger.warning("Search cache lookup skipped: %s", exc)
        return None
    if not doc:
        return None
    created = doc.get("created_at")
    if created is not None:
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - created).total_seconds()
        if age > SEARCH_CACHE_TTL_SECONDS:
            try:
                await get_db()[SEARCH_CACHE_COLLECTION].delete_one({"key": key})
            except Exception:  # noqa: BLE001 - best-effort eviction
                pass
            return None
    return doc


async def _cache_store(key: str, neutral_query: str, response: SearchResponse) -> None:
    """Persist the aggregated response; logs and swallows all errors."""
    try:
        now = datetime.now(timezone.utc)
        doc = {
            "key": key,
            "neutral_query": neutral_query,
            "query": response.query,
            "results": [study.model_dump() for study in response.results],
            "claims": [claim.model_dump() for claim in response.claims],
            "created_at": now,
            "updated_at": now,
        }
        await get_db()[SEARCH_CACHE_COLLECTION].update_one({"key": key}, {"$set": doc}, upsert=True)
        logger.info(
            "Cached search %s (%d studies / %d claims)",
            key,
            len(response.results),
            len(response.claims),
        )
    except Exception as exc:  # noqa: BLE001 - caching must not fail search
        logger.warning("Search cache store skipped: %s", exc)


def _build_study(
    paper: RawPaper, design: StudyDesign, study_id: str, is_fallback: bool = False
) -> Study:
    # Preserve null metadata: unknown years stay None (schema-nullable) so
    # missing years never masquerade as current-year publications.
    return Study(
        study_id=study_id,
        title=paper.title,
        authors=[Author(name=name) for name in paper.authors if name.strip()],
        year=paper.year,
        venue=paper.venue,
        doi=paper.doi,
        abstract=paper.snippet.strip() or "Not reported",
        url=paper.link,
        design=design,
        is_fallback=is_fallback,
    )


async def _extract_one(
    paper: RawPaper,
    semaphore: asyncio.Semaphore,
    intervention: str = "",
    outcome: str = "",
) -> tuple[Study, list[Claim]]:
    """Extract PICO + claims for one paper in a SINGLE LLM call.

    Never raises (structured fallbacks on error). Studies fan out via
    asyncio.gather bounded by the semaphore; individual LLM requests are
    further paced/retried inside the extraction service. The normalized
    intervention/outcome anchor direction polarity in the prompt. Study IDs
    are stable (DOI else title+year — no positional index), and heuristic
    fallback results are flagged `is_fallback=True` so they are served but
    never cached.
    """
    async with semaphore:
        study_id = _make_study_id(paper.title, paper.year, paper.doi)
        try:
            design, claims, fallback = await _extract_study_unified_inner(
                paper.title, paper.snippet, study_id, intervention, outcome
            )
        except Exception as exc:  # noqa: BLE001 - per-paper resilience
            logger.warning("Unified extraction failed for %s: %s", study_id, exc)
            design, claims, fallback = _fallback_design(), [], True
        if not extraction_svc.is_llm_configured():
            fallback = True
        return _build_study(paper, design, study_id, is_fallback=fallback), claims


async def _persist_studies_and_claims(studies: list[Study], claims: list[Claim]) -> None:
    """Best-effort Mongo upserts; logs and swallows all errors."""
    try:
        db = get_db()
        now = datetime.now(timezone.utc)
        for study in studies:
            doc = study.model_dump()
            doc["updated_at"] = now
            await db["studies"].update_one({"study_id": study.study_id}, {"$set": doc}, upsert=True)
        for claim in claims:
            doc = claim.model_dump()
            doc["updated_at"] = now
            await db["claims"].update_one({"claim_id": claim.claim_id}, {"$set": doc}, upsert=True)
        logger.info("Persisted %d studies / %d claims", len(studies), len(claims))
    except Exception as exc:  # noqa: BLE001 - persistence must not fail search
        logger.warning("Mongo persistence skipped: %s", exc)


async def _retrieve_papers(query: str, max_results: int) -> list[RawPaper]:
    """SerpApi primary, Semantic Scholar fallback + abstract backfill."""
    terms = decompose_query(query)
    papers: list[RawPaper] = []

    if is_serpapi_configured():
        try:
            papers = await search_google_scholar(query, limit=min(max_results, SERPAPI_PAGE_CAP))
        except SearchProviderError as exc:
            # Includes RateLimitedError: fall through to S2 below.
            logger.warning("SerpApi failed, falling back to S2: %s", exc)
    else:
        logger.info("SERPAPI_API_KEY not set; using Semantic Scholar directly")

    s2_query = query if papers else (" ".join(terms) or query)
    if not papers or _needs_enrichment(papers):
        try:
            s2_papers = await search_semantic_scholar(s2_query, limit=max_results)
        except SearchProviderError as exc:
            logger.warning("Semantic Scholar fallback failed: %s", exc)
            s2_papers = []
        papers = (
            _merge_papers(papers, s2_papers, max_results) if papers else s2_papers[:max_results]
        )
    return _dedupe_papers(papers)[:max_results]


@router.post("/search", response_model=SearchResponse)
@limiter.limit("20/minute")
async def search_studies(request: Request, payload: SearchRequest) -> SearchResponse:
    """Live search: normalize -> retrieve -> concurrent extraction -> persist -> return."""
    parsed = parse_query(payload.query)
    logger.info(
        "Normalized query: neutral=%r intervention=%r outcome=%r direction=%s",
        parsed.neutral_search_query,
        parsed.intervention,
        parsed.outcome,
        parsed.expected_direction,
    )
    neutral = parsed.neutral_search_query or payload.query
    cache_key = _search_cache_key(neutral)
    cached_doc = await _cache_lookup(cache_key)
    if cached_doc is not None:
        cached = _coerce_cached_response(cached_doc, payload.query, payload.max_results)
        if cached is not None:
            logger.info("Search cache hit for %r", neutral)
            return cached
        logger.info("Ignoring invalid cache entry for %r", neutral)

    papers = await _retrieve_papers(neutral, payload.max_results)
    if not papers:
        raise HTTPException(
            status_code=502,
            detail=(
                "Literature search returned no papers. Providers may be "
                "unreachable, rate-limited, or unconfigured."
            ),
        )

    semaphore = asyncio.Semaphore(4)
    auth_failures_before = extraction_svc.AUTH_FAILURE_COUNT
    # Parallel extraction: all papers in the payload are fetched and parsed
    # concurrently via extract_study_unified (bounded by the semaphore to
    # avoid tripping provider rate limits).
    tasks = [
        _extract_one(paper, semaphore, parsed.intervention, parsed.outcome)
        for paper in papers
    ]
    processed = await asyncio.gather(*tasks)
    studies = [study for study, _ in processed]
    claims = [claim for _, paper_claims in processed for claim in paper_claims]

    if (
        extraction_svc.AUTH_FAILURE_COUNT > auth_failures_before
        and not _is_cacheable(studies, claims)
    ):
        # The provider rejected our credentials: every extraction fell back to
        # hollow records. Say so loudly (with the fix) instead of serving 10
        # empty "Not reported" cards with HTTP 200.
        raise HTTPException(
            status_code=502,
            detail=(
                "LLM authentication failed: the provider rejected the configured "
                "API key (401 Invalid API Key), so no study could be analyzed. "
                "Check GROQ_API_KEYS / GROQ_API_KEY / OPENAI_API_KEY in "
                "backend/.env (Groq keys start with gsk_ and are short — "
                "re-paste a fresh key from console.groq.com), then restart "
                "the backend."
            ),
        )

    response = SearchResponse(query=payload.query, results=studies, claims=claims)
    await _persist_studies_and_claims(studies, claims)
    if _is_cacheable(studies, claims):
        await _cache_store(cache_key, neutral, response)
    else:
        logger.info("Skipping cache store for %r (no extraction signal)", neutral)
    return response
