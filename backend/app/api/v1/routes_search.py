"""POST /api/v1/search — live literature search + structured extraction.

Pipeline:
  1. Decompose the natural-language query into keyword fallback terms.
  2. Retrieve papers via SerpApi Scholar, with Semantic Scholar fallback
     (also used to backfill truncated/missing SerpApi abstracts).
  3. Run unified single-call PICO+claim extraction concurrently (bounded semaphore).
  4. Best-effort upsert of Study/Claim docs into MongoDB.
  5. Return validated `Study` + `Claim` arrays (persistence never 500s).
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.db.mongo import get_db
from app.models.claim import Claim
from app.models.study import Author, Study, StudyDesign
from app.services.common import (
    RawPaper,
    SearchProviderError,
    decompose_query,
    normalize_title,
)
from app.services.extraction import _fallback_design, extract_study_unified
from app.services.search_s2 import search_semantic_scholar
from app.services.search_serp import is_serpapi_configured, search_google_scholar

logger = logging.getLogger(__name__)

router = APIRouter(tags=["search"])

MAX_CONCURRENT_EXTRACTIONS = 3
SERPAPI_PAGE_CAP = 20


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    query: str = Field(min_length=1)
    max_results: int = Field(default=10, ge=1, le=50)


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


def _make_study_id(title: str, year: int | None, index: int) -> str:
    digest = hashlib.sha1(f"{title}|{year}|{index}".encode("utf-8")).hexdigest()
    return f"study-{digest[:12]}"


def _build_study(paper: RawPaper, design: StudyDesign, study_id: str) -> Study:
    year = paper.year or datetime.now(timezone.utc).year  # schema requires int
    return Study(
        study_id=study_id,
        title=paper.title,
        authors=[Author(name=name) for name in paper.authors if name.strip()],
        year=year,
        venue=paper.venue,
        doi=paper.doi,
        abstract=paper.snippet.strip() or "Not reported",
        url=paper.link,
        design=design,
    )


async def _extract_one(
    paper: RawPaper, semaphore: asyncio.Semaphore, index: int
) -> tuple[Study, list[Claim]]:
    """Extract PICO + claims for one paper in a SINGLE LLM call.

    Never raises (structured fallbacks on error). Studies fan out via
    asyncio.gather bounded by the semaphore; individual LLM requests are
    further paced/retried inside the extraction service.
    """
    async with semaphore:
        study_id = _make_study_id(paper.title, paper.year, index)
        try:
            design, claims = await extract_study_unified(
                paper.title, paper.snippet, study_id
            )
        except Exception as exc:  # noqa: BLE001 - per-paper resilience
            logger.warning("Unified extraction failed for %s: %s", study_id, exc)
            design, claims = _fallback_design(), []
        return _build_study(paper, design, study_id), claims


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
async def search_studies(payload: SearchRequest) -> SearchResponse:
    """Live search: retrieve -> concurrent extraction -> persist -> return."""
    papers = await _retrieve_papers(payload.query, payload.max_results)
    if not papers:
        raise HTTPException(
            status_code=502,
            detail=(
                "Literature search returned no papers. Providers may be "
                "unreachable, rate-limited, or unconfigured."
            ),
        )

    semaphore = asyncio.Semaphore(MAX_CONCURRENT_EXTRACTIONS)
    processed = await asyncio.gather(
        *(_extract_one(paper, semaphore, i) for i, paper in enumerate(papers))
    )
    studies = [study for study, _ in processed]
    claims = [claim for _, paper_claims in processed for claim in paper_claims]

    await _persist_studies_and_claims(studies, claims)
    return SearchResponse(query=payload.query, results=studies, claims=claims)
