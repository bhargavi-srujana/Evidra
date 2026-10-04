"""Live literature search via SerpApi's Google Scholar engine.

Docs: https://serpapi.com/google-scholar-api
"""

from __future__ import annotations

import logging
import re

import httpx

from app.core.config import get_settings
from app.services.common import (
    RateLimitedError,
    RawPaper,
    SearchProviderError,
)

logger = logging.getLogger(__name__)

SERPAPI_ENDPOINT = "https://serpapi.com/search.json"
_REQUEST_TIMEOUT = httpx.Timeout(20.0, connect=5.0)

_YEAR_RE = re.compile(r"\b(18\d{2}|19\d{2}|20\d{2}|2100)\b")
_DOI_RE = re.compile(r"10\.\d{4,9}/[^\s\"'<>)\]]+", re.IGNORECASE)


def is_serpapi_configured() -> bool:
    """True when a SerpApi key is present (non-empty)."""
    return bool(get_settings().SERPAPI_API_KEY.strip())


def _extract_year(summary: str) -> int | None:
    match = _YEAR_RE.search(summary)
    if not match:
        return None
    year = int(match.group(0))
    return year if 1800 <= year <= 2100 else None


def _extract_venue(summary: str) -> str | None:
    """Best-effort venue from SerpApi's `publication_info.summary`.

    Typical shape: "A Author, B Author - Journal of X, 2020 - Publisher".
    The venue is usually the middle dash-separated segment minus the year.
    """
    parts = [p.strip() for p in summary.split(" - ") if p.strip()]
    if len(parts) < 2:
        return None
    candidate = parts[1] if len(parts) >= 3 else parts[-1]
    candidate = _YEAR_RE.sub("", candidate).strip(" ,;")
    return candidate or None


def _extract_doi(result: dict) -> str | None:
    candidates: list[str] = []
    if isinstance(result.get("link"), str):
        candidates.append(result["link"])
    for resource in result.get("resources") or []:
        if isinstance(resource, dict) and isinstance(resource.get("link"), str):
            candidates.append(resource["link"])
    for url in candidates:
        match = _DOI_RE.search(url)
        if match:
            return match.group(0).rstrip(".,;").lower()
    return None


def _parse_result(result: dict) -> RawPaper | None:
    title = str(result.get("title") or "").strip()
    if not title:
        return None
    pub = result.get("publication_info") or {}
    summary = str(pub.get("summary") or "")
    authors = [
        str(a.get("name") or "").strip()
        for a in (pub.get("authors") or [])
        if isinstance(a, dict) and str(a.get("name") or "").strip()
    ]
    try:
        return RawPaper(
            title=title,
            snippet=str(result.get("snippet") or ""),
            authors=authors,
            year=_extract_year(summary),
            venue=_extract_venue(summary),
            doi=_extract_doi(result),
            link=str(result.get("link") or "") or None,
            source="serpapi",
        )
    except Exception as exc:  # noqa: BLE001 - one bad record must not fail search
        logger.warning("Skipping unparseable SerpApi record %r: %s", title[:60], exc)
        return None


async def search_google_scholar(query: str, limit: int = 15) -> list[RawPaper]:
    """Search Google Scholar via SerpApi, returning normalized raw papers.

    Raises:
        SearchProviderError: transport errors, non-200 responses, API errors.
        RateLimitedError: HTTP 429 or quota-exhaustion payloads.
    """
    settings = get_settings()
    api_key = settings.SERPAPI_API_KEY.strip()
    if not api_key:
        raise SearchProviderError("serpapi: SERPAPI_API_KEY is not configured")
    limit = max(1, min(limit, 20))  # SerpApi Scholar pages cap at ~20 per request

    params = {
        "engine": "google_scholar",
        "q": query,
        "api_key": api_key,
        "num": limit,
        "hl": "en",
    }
    try:
        async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
            response = await client.get(SERPAPI_ENDPOINT, params=params)
    except httpx.HTTPError as exc:
        raise SearchProviderError(f"serpapi: transport error: {exc}") from exc

    if response.status_code == 429:
        raise RateLimitedError("serpapi")
    if response.status_code != 200:
        raise SearchProviderError(f"serpapi: HTTP {response.status_code}: {response.text[:300]}")

    try:
        data = response.json()
    except ValueError as exc:
        raise SearchProviderError(f"serpapi: invalid JSON response: {exc}") from exc

    if isinstance(data.get("error"), str) and data["error"]:
        err = data["error"]
        if "quota" in err.lower() or "limit" in err.lower():
            raise RateLimitedError("serpapi", err[:200])
        raise SearchProviderError(f"serpapi: API error: {err[:300]}")

    papers = [
        paper
        for result in (data.get("organic_results") or [])[:limit]
        if isinstance(result, dict) and (paper := _parse_result(result)) is not None
    ]
    logger.info("SerpApi Scholar: %d papers for %r", len(papers), query[:80])
    return papers
