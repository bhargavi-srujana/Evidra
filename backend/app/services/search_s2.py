"""Fallback literature search via the Semantic Scholar Graph API.

Docs: https://api.semanticscholar.org/graph/v1
Used when SerpApi abstracts are truncated/missing, rate-limited, or unkeyed.
The API is usable anonymously; an `S2_API_KEY` raises rate limits when set.
"""

from __future__ import annotations

import logging

import httpx

from app.core.config import get_settings
from app.services.common import (
    RateLimitedError,
    RawPaper,
    SearchProviderError,
)

logger = logging.getLogger(__name__)

S2_SEARCH_ENDPOINT = "https://api.semanticscholar.org/graph/v1/paper/search"
_REQUEST_TIMEOUT = httpx.Timeout(20.0, connect=5.0)
_FIELDS = "title,abstract,authors,year,venue,externalIds,url,openAccessPdf"


def _parse_year(value: object) -> int | None:
    if isinstance(value, int) and 1800 <= value <= 2100:
        return value
    return None


def _parse_record(record: dict) -> RawPaper | None:
    title = str(record.get("title") or "").strip()
    if not title:
        return None
    authors = [
        str(a.get("name") or "").strip()
        for a in (record.get("authors") or [])
        if isinstance(a, dict) and str(a.get("name") or "").strip()
    ]
    external_ids = record.get("externalIds") or {}
    doi = external_ids.get("DOI") if isinstance(external_ids, dict) else None
    pdf = record.get("openAccessPdf") or {}
    url = record.get("url") or (pdf.get("url") if isinstance(pdf, dict) else None)
    try:
        return RawPaper(
            title=title,
            snippet=str(record.get("abstract") or ""),
            authors=authors,
            year=_parse_year(record.get("year")),
            venue=str(record.get("venue") or "").strip() or None,
            doi=str(doi).strip().lower() or None if doi else None,
            link=str(url or "").strip() or None,
            source="s2",
        )
    except Exception as exc:  # noqa: BLE001 - one bad record must not fail search
        logger.warning("Skipping unparseable S2 record %r: %s", title[:60], exc)
        return None


async def search_semantic_scholar(query: str, limit: int = 10) -> list[RawPaper]:
    """Full-text relevance search over Semantic Scholar, normalized output.

    Raises:
        SearchProviderError: transport errors, non-200 responses.
        RateLimitedError: HTTP 429 (callers should back off / surface 502).
    """
    settings = get_settings()
    limit = max(1, min(limit, 100))
    headers = {"Accept": "application/json"}
    if settings.S2_API_KEY.strip():
        headers["x-api-key"] = settings.S2_API_KEY.strip()
    params = {"query": query, "limit": limit, "fields": _FIELDS}

    try:
        async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
            response = await client.get(S2_SEARCH_ENDPOINT, params=params, headers=headers)
    except httpx.HTTPError as exc:
        raise SearchProviderError(f"s2: transport error: {exc}") from exc

    if response.status_code == 429:
        retry_after = response.headers.get("retry-after")
        raise RateLimitedError("s2", retry_after=retry_after)
    if response.status_code != 200:
        raise SearchProviderError(f"s2: HTTP {response.status_code}: {response.text[:300]}")

    try:
        data = response.json()
    except ValueError as exc:
        raise SearchProviderError(f"s2: invalid JSON response: {exc}") from exc

    papers = [
        paper
        for record in (data.get("data") or [])[:limit]
        if isinstance(record, dict) and (paper := _parse_record(record)) is not None
    ]
    logger.info("Semantic Scholar: %d papers for %r", len(papers), query[:80])
    return papers
