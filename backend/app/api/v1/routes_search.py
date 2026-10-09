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
from datetime import UTC, datetime

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
from app.services.query_parser import aparse_query
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

    query: str = Field(min_length=1, max_length=2000)
    max_results: int = Field(default=6, ge=1, le=50)


class SearchResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str
    results: list[Study]
    claims: list[Claim] = Field(default_factory=list)
    # Anchor provenance: how effect directions in `claims` are to be read.
    # "Positive" means the intervention below raises the outcome; opposite
    # phrasings ("do men…" vs "do women…") anchor opposite verdicts by
    # design, so the UI surfaces this to avoid misreading mirrored counts.
    intervention: str = ""
    outcome: str = ""
    expected_direction: str = "unclear"
    anchor_question: str = ""


def _needs_enrichment(papers: list[RawPaper]) -> bool:
    """True when any SerpApi record lacks a usable abstract."""
    return any(p.abstract_missing() for p in papers)


def _dedupe_papers(papers: list[RawPaper]) -> list[RawPaper]:
    seen_titles: set[str] = set()
    seen_dois: set[str] = set()
    unique: list[RawPaper] = []
    for paper in papers:
        doi_key = (paper.doi or "").strip().lower().rstrip(".,;")
        if doi_key:
            if doi_key in seen_dois:
                continue
            seen_dois.add(doi_key)
        key = normalize_title(paper.title)
        if not key:
            continue
        if key in seen_titles:
            continue
        seen_titles.add(key)
        unique.append(paper)
    return unique


def _merge_papers(primary: list[RawPaper], fallback: list[RawPaper], limit: int) -> list[RawPaper]:
    """Backfill missing SerpApi abstracts from S2, then top up with S2-only hits."""
    by_title = {normalize_title(p.title): p for p in primary if normalize_title(p.title)}
    by_doi = {
        (p.doi or "").strip().lower().rstrip(".,;"): p
        for p in primary
        if (p.doi or "").strip()
    }
    extras: list[RawPaper] = []
    for paper in fallback:
        key = normalize_title(paper.title)
        doi_key = (paper.doi or "").strip().lower().rstrip(".,;")
        existing = by_title.get(key) if key else None
        if existing is None and doi_key:
            existing = by_doi.get(doi_key)
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


def _search_cache_key(
    neutral_query: str,
    intervention: str = "",
    outcome: str = "",
    direction: str = "unclear",
    max_results: int = 6,
) -> str:
    """Stable cache key: normalized neutral query, case/whitespace-insensitive.

    Versioned (`search-v4-…`): the key scopes on polarity (intervention /
    outcome / expected direction) and on max_results — opposite questions
    must never share a response, and a response cached at a small limit must
    never satisfy a later request for more studies (entries only slice down,
    never expand). Pre-v4 entries never hit.
    """
    normalized = " ".join((neutral_query or "").strip().lower().split())
    scope = "|".join(
        [
            normalized,
            " ".join((intervention or "").strip().lower().split()),
            " ".join((outcome or "").strip().lower().split()),
            (direction or "unclear").strip().lower(),
            str(max(1, int(max_results))),
        ]
    )
    digest = hashlib.sha1(scope.encode()).hexdigest()
    return f"search-v4-{digest[:16]}"


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
    # Self-healing: entries written before the empty-claim backstop may leave
    # retained studies with zero claims (papers with no visible conclusion).
    # Treat as a miss so the query re-extracts fresh instead of serving the
    # degraded response.
    claimed_ids = {claim.study_id for claim in claims}
    if any(study.study_id not in claimed_ids for study in studies):
        return None
    return SearchResponse(
        query=query,
        results=studies,
        claims=claims,
        intervention=str(doc.get("intervention", "") or ""),
        outcome=str(doc.get("outcome", "") or ""),
        expected_direction=str(doc.get("expected_direction", "") or "unclear"),
        anchor_question=str(doc.get("anchor_question", "") or ""),
    )


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
            created = created.replace(tzinfo=UTC)
        age = (datetime.now(UTC) - created).total_seconds()
        if age > SEARCH_CACHE_TTL_SECONDS:
            try:
                await get_db()[SEARCH_CACHE_COLLECTION].delete_one({"key": key})
            except Exception as exc:  # noqa: BLE001 - best-effort eviction
                logger.debug("Search cache eviction skipped for %s: %s", key, exc)
            return None
    return doc


async def _cache_store(
    key: str,
    neutral_query: str,
    response: SearchResponse,
    parsed=None,  # type: ignore[no-untyped-def]
) -> None:
    """Persist the aggregated response; logs and swallows all errors."""
    try:
        now = datetime.now(UTC)
        doc = {
            "key": key,
            "neutral_query": neutral_query,
            "query": response.query,
            "results": [study.model_dump() for study in response.results],
            "claims": [claim.model_dump() for claim in response.claims],
            "intervention": response.intervention or (parsed.intervention if parsed else ""),
            "outcome": response.outcome or (parsed.outcome if parsed else ""),
            "expected_direction": response.expected_direction
            or (parsed.expected_direction if parsed else "unclear"),
            "anchor_question": response.anchor_question
            or (parsed.anchor_question if parsed else ""),
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
    anchor_question: str = "",
) -> tuple[Study, list[Claim], bool]:
    """Extract PICO + claims for one paper in a SINGLE LLM call.

    Never raises (structured fallbacks on error). Returns
    `(study, claims, auth_failed)` where `auth_failed` is True only when
    this paper saw a credential rejection — per-paper provenance so
    concurrent searches cannot misattribute each other's failures.
    Study IDs are stable (DOI else title+year), and heuristic fallback
    results are flagged `is_fallback=True` so they are served but never
    cached.
    """
    async with semaphore:
        study_id = _make_study_id(paper.title, paper.year, paper.doi)
        try:
            result = await _extract_study_unified_inner(
                paper.title,
                paper.snippet,
                study_id,
                intervention,
                outcome,
                anchor_question=anchor_question,
            )
            if len(result) == 4:
                design, claims, fallback, auth_failed = result
            else:  # backward-compat with 3-tuple during rollout
                design, claims, fallback = result  # type: ignore[misc]
                auth_failed = False
        except Exception as exc:  # noqa: BLE001 - per-paper resilience
            logger.warning("Unified extraction failed for %s: %s", study_id, exc)
            design, claims, fallback = _fallback_design(), [], True
            auth_failed = extraction_svc._is_auth_error(exc)
        if not extraction_svc.is_llm_configured():
            fallback = True
        return _build_study(paper, design, study_id, is_fallback=fallback), claims, auth_failed


async def _persist_studies_and_claims(studies: list[Study], claims: list[Claim]) -> None:
    """Best-effort Mongo upserts; logs and swallows all errors."""
    try:
        db = get_db()
        now = datetime.now(UTC)
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


# Singleflight: concurrent identical queries share one pipeline run instead
# of each paying full retrieval + LLM extraction (stampede / quota burn).
# Waiters shield-await the same task; cancelling a waiter never cancels the
# shared run. Entries are popped when the run settles.
_inflight_searches: dict[str, asyncio.Task[SearchResponse]] = {}


async def _run_singleflight(key: str, factory) -> SearchResponse:  # type: ignore[no-untyped-def]
    try:
        return await factory()
    finally:
        if _inflight_searches.get(key) is asyncio.current_task():
            _inflight_searches.pop(key, None)


async def _search_fresh(
    payload: SearchRequest, neutral: str, cache_key: str, parsed
) -> SearchResponse:  # type: ignore[no-untyped-def]
    """Cache-miss path: retrieve -> concurrent extraction -> persist -> store."""
    try:
        papers = await _retrieve_papers(neutral, payload.max_results)
    except HTTPException:
        raise
    except SearchProviderError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Literature providers unavailable: {exc}",
        ) from exc
    except Exception as exc:
        logger.warning("Literature retrieval failed for %r: %s", neutral, exc)
        raise HTTPException(
            status_code=502,
            detail="Literature search failed unexpectedly.",
        ) from exc
    if not papers:
        raise HTTPException(
            status_code=502,
            detail=(
                "Literature search returned no papers. Providers may be "
                "unreachable, rate-limited, or unconfigured."
            ),
        )

    semaphore = asyncio.Semaphore(MAX_CONCURRENT_EXTRACTIONS)
    # Parallel extraction: all papers in the payload are fetched and parsed
    # concurrently via extract_study_unified (bounded by the semaphore to
    # avoid tripping provider rate limits).
    tasks = [
        _extract_one(
            paper, semaphore, parsed.intervention, parsed.outcome, parsed.anchor_question
        )
        for paper in papers
    ]
    processed = await asyncio.gather(*tasks)
    studies = [study for study, _, _ in processed]
    claims = [claim for _, paper_claims, _ in processed for claim in paper_claims]
    auth_failed = any(flag for _, _, flag in processed)

    if not _is_cacheable(studies, claims):
        if auth_failed:
            # The provider rejected our credentials on this run: every
            # extraction fell back to hollow records. Say so loudly (with the
            # fix) instead of serving empty "Not reported" cards with 200.
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
        if not extraction_svc.is_llm_configured():
            raise HTTPException(
                status_code=502,
                detail=(
                    "LLM is not configured (no API key), so studies could not be "
                    "analyzed. Set GROQ_API_KEYS / GROQ_API_KEY / OPENAI_API_KEY "
                    "in backend/.env and restart the backend."
                ),
            )

    response = SearchResponse(
        query=payload.query,
        results=studies,
        claims=claims,
        intervention=parsed.intervention,
        outcome=parsed.outcome,
        expected_direction=parsed.expected_direction,
        anchor_question=parsed.anchor_question,
    )
    await _persist_studies_and_claims(studies, claims)
    if _is_cacheable(studies, claims):
        await _cache_store(cache_key, neutral, response, parsed)
    else:
        logger.info("Skipping cache store for %r (no extraction signal)", neutral)
    return response


@router.post("/search", response_model=SearchResponse)
@limiter.limit("20/minute")
async def search_studies(request: Request, payload: SearchRequest) -> SearchResponse:
    """Live search: normalize -> cache -> coalesced fresh run -> return."""
    # Async parse: rule shapes cost zero quota; missed shapes spend one
    # cached LLM call (flag-gated) so extraction anchors instead of drifting.
    parsed = await aparse_query(payload.query)
    logger.info(
        "Normalized query: neutral=%r intervention=%r outcome=%r direction=%s",
        parsed.neutral_search_query,
        parsed.intervention,
        parsed.outcome,
        parsed.expected_direction,
    )
    neutral = parsed.neutral_search_query or payload.query
    cache_key = _search_cache_key(
        neutral,
        parsed.intervention,
        parsed.outcome,
        parsed.expected_direction,
        payload.max_results,
    )
    cached_doc = await _cache_lookup(cache_key)
    if cached_doc is not None:
        cached = _coerce_cached_response(cached_doc, payload.query, payload.max_results)
        if cached is not None:
            logger.info("Search cache hit for %r", neutral)
            return cached
        logger.info("Ignoring invalid cache entry for %r", neutral)

    task = _inflight_searches.get(cache_key)
    if task is None:
        task = asyncio.ensure_future(
            _run_singleflight(cache_key, lambda: _search_fresh(payload, neutral, cache_key, parsed))
        )
        _inflight_searches[cache_key] = task
    else:
        logger.info("Coalescing concurrent search for %r", neutral)
    # Shield the shared run: a single waiter's disconnect must not cancel
    # extraction for the other coalesced callers.
    return await asyncio.shield(task)
