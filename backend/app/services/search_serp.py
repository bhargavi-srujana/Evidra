"""Live literature search via SerpApi's Google Scholar engine.

Docs: https://serpapi.com/google-scholar-api
"""

from __future__ import annotations

import ipaddress
import logging
import re
import socket
from urllib.parse import urlparse

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

# Strategy 2 (open-access PDF parsing): aggressive 3s fetch timeout + char
# cap so a slow/huge PDF can never stall search — on timeout we skip the
# full-text download and fall back to SerpApi title/snippet metadata.
_PDF_TIMEOUT = httpx.Timeout(3.0)
PDF_MAX_CHARS = 4000

# Hard cap on downloaded PDF bytes so a malicious/huge file can never
# exhaust server memory. Enforced while streaming (plus Content-Length check).
PDF_MAX_BYTES = 10_000_000

# SSRF blocklist: loopback, RFC-1918 private ranges, and cloud metadata IP.
_BLOCKED_NETWORKS = (
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.169.254/32"),
)

_MAX_REDIRECTS = 3


def validate_url_safety(url: str) -> None:
    """Reject non-http(s) URLs and URLs resolving to private/loopback IPs.

    Raises:
        ValueError: if the scheme is not http/https, the URL has no
            hostname, DNS resolution fails, or any resolved IP falls
            within a blocked range (127/8, 10/8, 172.16/12, 192.168/16,
            or 169.254.169.254).
    """
    if not isinstance(url, str) or not url.strip():
        raise ValueError("URL must be a non-empty string")
    parsed = urlparse(url.strip())
    if parsed.scheme.lower() not in ("http", "https"):
        raise ValueError(f"Blocked non-http(s) scheme: {parsed.scheme!r}")
    host = parsed.hostname
    if not host:
        raise ValueError("URL has no hostname")

    # Fast path: literal IP in the URL (handles brackets already stripped
    # by urlparse.hostname).
    try:
        literal_ip = ipaddress.ip_address(host)
    except ValueError:
        literal_ip = None
    if literal_ip is not None:
        for net in _BLOCKED_NETWORKS:
            if literal_ip.version == net.version and literal_ip in net:
                raise ValueError(f"Blocked IP {literal_ip} in range {net}")
        return

    # Resolve hostnames to IPs and check every result (fail closed).
    try:
        addr_infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise ValueError(f"DNS resolution failed for {host!r}: {exc}") from exc
    if not addr_infos:
        raise ValueError(f"DNS resolution returned no addresses for {host!r}")
    for info in addr_infos:
        sockaddr = info[4]
        if not sockaddr:
            continue
        try:
            resolved_ip = ipaddress.ip_address(sockaddr[0])
        except ValueError:
            continue
        for net in _BLOCKED_NETWORKS:
            if resolved_ip.version == net.version and resolved_ip in net:
                raise ValueError(
                    f"Blocked host {host!r} resolves to {resolved_ip} in range {net}"
                )

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


def _find_pdf_link(result: dict) -> str | None:
    """First open-access PDF URL in the SerpApi `resources` array.

    A resource counts as a PDF when its URL path ends with `.pdf` or its
    `file_format` is `"pdf"` (case-insensitive). Falls back to the top-level
    `link` when that itself points at a `.pdf` file.
    """
    resources = result.get("resources") or []
    if isinstance(resources, list):
        for resource in resources:
            if not isinstance(resource, dict):
                continue
            link = resource.get("link")
            if not isinstance(link, str) or not link.strip():
                continue
            file_format = str(resource.get("file_format") or "").strip().lower()
            path = link.strip().lower().split("?", 1)[0].split("#", 1)[0]
            if path.endswith(".pdf") or file_format == "pdf":
                return link.strip()
    top_link = result.get("link")
    if isinstance(top_link, str) and top_link.strip():
        path = top_link.strip().lower().split("?", 1)[0].split("#", 1)[0]
        if path.endswith(".pdf"):
            return top_link.strip()
    return None


async def fetch_pdf_text_from_link(pdf_url: str, max_pages: int = 2) -> str:
    """Fetch an open-access PDF and return up to 4,000 chars of its text.

    SSRF-safe: `validate_url_safety` runs before any request (and on each
    manual redirect target), redirects are NOT followed automatically
    (`follow_redirects=False`), a HEAD request must report an
    `application/pdf` content-type, and the GET body is streamed with a
    hard 10MB cap. Downloads with `httpx.AsyncClient` (timeout=3.0) and
    parses the first `max_pages` pages with PyMuPDF
    (`fitz.open(stream=..., filetype="pdf")`). Any download or parsing
    failure returns "" so callers can fall back to metadata-only context.
    A PDF server taking longer than 3 seconds is skipped immediately.
    """
    if not isinstance(pdf_url, str) or not pdf_url.strip():
        return ""
    url = pdf_url.strip()
    try:
        validate_url_safety(url)
    except ValueError as exc:
        logger.warning("Blocked unsafe PDF URL %r: %s", url[:80], exc)
        return ""
    max_pages = max(1, int(max_pages))
    try:
        async with httpx.AsyncClient(
            follow_redirects=False, timeout=3.0
        ) as client:
            # Manual redirect chain so every hop is SSRF-validated.
            redirects_followed = 0
            while redirects_followed <= _MAX_REDIRECTS:
                try:
                    head_resp = await client.head(url)
                except httpx.HTTPError as exc:
                    logger.warning("PDF HEAD failed for %r: %s", url[:80], exc)
                    break  # fall through to GET; GET content-type is checked too
                else:
                    if head_resp.status_code in (301, 302, 303, 307, 308):
                        location = head_resp.headers.get("location")
                        if not location:
                            return ""
                        # Resolve relative redirects against the current URL.
                        next_url = (
                            location
                            if urlparse(location).netloc
                            else httpx.URL(url).join(location).__str__()
                        )
                        try:
                            validate_url_safety(next_url)
                        except ValueError as exc:
                            logger.warning(
                                "Blocked unsafe PDF redirect %r -> %r: %s",
                                url[:80],
                                next_url[:80],
                                exc,
                            )
                            return ""
                        url = next_url
                        redirects_followed += 1
                        continue
                    if head_resp.status_code == 200:
                        content_type = head_resp.headers.get("content-type", "").lower()
                        if "application/pdf" not in content_type:
                            logger.warning(
                                "PDF HEAD content-type mismatch for %r: %r",
                                url[:80],
                                content_type[:80],
                            )
                            return ""
                    # Non-200/non-redirect HEAD (e.g. 405/501): fall through
                    # to GET, whose content-type is verified below.
                    break

            # Stream the GET body so a huge file can never fill memory.
            content = bytearray()
            try:
                async with client.stream("GET", url) as response:
                    if response.status_code in (301, 302, 303, 307, 308):
                        # No auto-follow: treat redirects as failures (already
                        # handled the HEAD chain above).
                        logger.warning(
                            "PDF GET redirect not followed for %r", url[:80]
                        )
                        return ""
                    if response.status_code != 200:
                        return ""
                    content_length = response.headers.get("content-length")
                    if content_length:
                        try:
                            if int(content_length) > PDF_MAX_BYTES:
                                logger.warning(
                                    "PDF too large (Content-Length %s) for %r",
                                    content_length,
                                    url[:80],
                                )
                                return ""
                        except ValueError:
                            pass
                    get_content_type = response.headers.get("content-type", "").lower()
                    if "application/pdf" not in get_content_type:
                        logger.warning(
                            "PDF GET content-type mismatch for %r: %r",
                            url[:80],
                            get_content_type[:80],
                        )
                        return ""
                    async for chunk in response.aiter_bytes(chunk_size=65536):
                        content.extend(chunk)
                        if len(content) > PDF_MAX_BYTES:
                            logger.warning(
                                "PDF exceeded %d bytes for %r; aborting",
                                PDF_MAX_BYTES,
                                url[:80],
                            )
                            return ""
            except httpx.HTTPError as exc:
                logger.warning("PDF fetch failed for %r: %s", url[:80], exc)
                return ""
        if not content:
            return ""
        try:
            import fitz  # PyMuPDF; imported lazily so search works without it
        except ImportError:
            try:
                import pymupdf as fitz  # type: ignore[no-redef]
            except ImportError:
                logger.warning("PyMuPDF not installed; skipping PDF fetch for %r", url[:80])
                return ""
        try:
            doc = fitz.open(stream=bytes(content), filetype="pdf")
        except Exception as exc:  # noqa: BLE001 - corrupt/HTML payloads are common
            logger.warning("PDF parse failed for %r: %s", url[:80], exc)
            return ""
        try:
            chunks: list[str] = []
            for page in doc[:max_pages]:
                try:
                    chunks.append(page.get_text() or "")
                except Exception:  # noqa: BLE001 - one bad page must not fail all
                    continue
            text = "\n".join(chunk.strip() for chunk in chunks if chunk.strip()).strip()
        finally:
            try:
                doc.close()
            except Exception:  # noqa: BLE001 - best-effort cleanup
                pass
        return text[:PDF_MAX_CHARS]
    except Exception as exc:  # noqa: BLE001 - PDF enrichment must never break search
        logger.warning("PDF fetch failed for %r: %s", url[:80], exc)
        return ""


async def get_rich_paper_context(serpapi_result: dict) -> str:
    """Build a high-character LLM payload from a raw SerpApi result.

    Strategy 1 (rich metadata): combines title + `publication_info.summary` +
    snippet into one context block. Strategy 2 (open-access PDF parsing):
    when `resources` contains a PDF link, fetches its first-2-pages text via
    `fetch_pdf_text_from_link` and appends it to the metadata context.
    Never raises; without a PDF link the metadata block alone is returned.
    """
    if not isinstance(serpapi_result, dict):
        return ""
    title = str(serpapi_result.get("title") or "").strip()
    pub = serpapi_result.get("publication_info") or {}
    summary = str(pub.get("summary") or "").strip() if isinstance(pub, dict) else ""
    snippet = str(serpapi_result.get("snippet") or "").strip()

    parts = []
    if title:
        parts.append(f"Title: {title}")
    if summary:
        parts.append(f"Summary: {summary}")
    if snippet:
        parts.append(f"Snippet: {snippet}")
    context = "\n".join(parts).strip()

    pdf_url = _find_pdf_link(serpapi_result)
    if pdf_url:
        pdf_text = await fetch_pdf_text_from_link(pdf_url)
        if pdf_text:
            context = f"{context}\n\nFull text (PDF first pages): {pdf_text}".strip()
    return context


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
