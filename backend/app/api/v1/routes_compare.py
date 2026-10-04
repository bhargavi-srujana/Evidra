"""POST /api/v1/compare — methodology-aware contradiction engine.

Pipeline:
  1. Resolve studies (Mongo by `study_ids`) and claims (request body or Mongo).
  2. Cluster claims into semantic topics.
  3. Pair opposing claims (INCREASES vs DECREASES/NO_EFFECT) within each
     cluster and run concurrent PICO-based contradiction analysis.
  4. Detect corpus-level research gaps.
  5. Return a ComparisonMatrix (superset of the Phase 1 shape, so existing
     clients reading `contradictions`/`summary` keep working).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.db.mongo import get_db
from app.models.claim import Claim, EffectDirection
from app.models.comparison import ComparisonMatrix, EvidenceSummary
from app.models.study import Study
from app.services.comparison import analyze_contradictions, cluster_claims
from app.services.gap_analysis import detect_research_gaps

logger = logging.getLogger(__name__)

router = APIRouter(tags=["compare"])

MAX_PAIRS = 10
MAX_CONCURRENT_COMPARISONS = 4

_POSITIVE = {EffectDirection.INCREASES}
_NEGATIVE = {EffectDirection.DECREASES, EffectDirection.NO_EFFECT}


class CompareRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    study_ids: list[str] = Field(min_length=2, max_length=20)
    claims: list[Claim] | None = None


def _coerce_study(doc: dict[str, Any]) -> Study | None:
    doc = {k: v for k, v in doc.items() if k not in ("_id", "updated_at")}
    try:
        return Study(**doc)
    except Exception as exc:  # noqa: BLE001 - skip corrupt docs, report if all fail
        logger.warning("Skipping invalid study doc %r: %s", doc.get("study_id"), exc)
        return None


def _coerce_claim(doc: dict[str, Any]) -> Claim | None:
    doc = {k: v for k, v in doc.items() if k not in ("_id", "updated_at")}
    try:
        return Claim(**doc)
    except Exception as exc:  # noqa: BLE001 - skip corrupt docs
        logger.warning("Skipping invalid claim doc %r: %s", doc.get("claim_id"), exc)
        return None


async def _fetch_studies(study_ids: list[str]) -> list[Study]:
    try:
        db = get_db()
        docs = (
            await db["studies"]
            .find({"study_id": {"$in": study_ids}})
            .to_list(length=len(study_ids))
        )
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Study store unavailable: {exc}. Run POST /search first.",
        ) from exc
    by_id = {s.study_id: s for s in (_coerce_study(d) for d in docs) if s}
    missing = [sid for sid in study_ids if sid not in by_id]
    if missing:
        raise HTTPException(
            status_code=404,
            detail=f"Studies not found: {missing}. Run POST /search first.",
        )
    return [by_id[sid] for sid in study_ids]


async def _fetch_claims(study_ids: list[str]) -> list[Claim]:
    try:
        db = get_db()
        docs = await db["claims"].find({"study_id": {"$in": study_ids}}).to_list(length=500)
    except Exception as exc:  # noqa: BLE001 - claims optional; continue without
        logger.warning("Claim fetch skipped (store unavailable): %s", exc)
        return []
    wanted = set(study_ids)
    return [c for d in docs if (c := _coerce_claim(d)) is not None and c.study_id in wanted]


def _opposing_pairs(
    clusters_claims: list[tuple[str, list[Claim]]],
    studies_by_id: dict[str, Study],
) -> list[tuple[Study, Claim, Study, Claim]]:
    """Cross-product of positive x negative claims per cluster, top-ranked."""
    candidates: list[tuple[float, Study, Claim, Study, Claim]] = []
    for _, members in clusters_claims:
        positives = [c for c in members if c.effect_direction in _POSITIVE]
        negatives = [c for c in members if c.effect_direction in _NEGATIVE]
        for claim_a in positives:
            study_a = studies_by_id.get(claim_a.study_id)
            if study_a is None:
                continue
            for claim_b in negatives:
                if claim_a.study_id == claim_b.study_id:
                    continue  # same-study tension is not a contradiction
                study_b = studies_by_id.get(claim_b.study_id)
                if study_b is None:
                    continue
                score = claim_a.confidence_score + claim_b.confidence_score
                candidates.append((score, study_a, claim_a, study_b, claim_b))
    candidates.sort(key=lambda item: item[0], reverse=True)
    return [(a, ca, b, cb) for _, a, ca, b, cb in candidates[:MAX_PAIRS]]


def _build_summary(studies: list[Study], claims: list[Claim], gaps: list[str]) -> EvidenceSummary:
    directions = [c.effect_direction for c in claims]
    return EvidenceSummary(
        total_studies=len(studies),
        positive_count=sum(1 for d in directions if d == EffectDirection.INCREASES),
        conditional_count=sum(1 for d in directions if d == EffectDirection.CONDITIONAL),
        negative_count=sum(
            1 for d in directions if d in (EffectDirection.DECREASES, EffectDirection.NO_EFFECT)
        ),
        key_gaps=gaps,
    )


@router.post("/compare", response_model=ComparisonMatrix)
async def compare_studies(payload: CompareRequest) -> ComparisonMatrix:
    """Cluster claims, contrast opposing pairs, surface gaps."""
    studies = await _fetch_studies(payload.study_ids)
    studies_by_id = {s.study_id: s for s in studies}

    if payload.claims is not None:
        claims = [c for c in payload.claims if c.study_id in studies_by_id]
    else:
        claims = await _fetch_claims(payload.study_ids)

    clusters = await cluster_claims(claims)
    claims_by_id = {c.claim_id: c for c in claims}
    clusters_claims = [
        (
            cluster.cluster_id,
            [claims_by_id[cid] for cid in cluster.claim_ids if cid in claims_by_id],
        )
        for cluster in clusters
    ]

    pairs = _opposing_pairs(clusters_claims, studies_by_id)
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_COMPARISONS)

    async def _run(study_a: Study, claim_a: Claim, study_b: Study, claim_b: Claim):
        async with semaphore:
            return await analyze_contradictions(study_a, claim_a, study_b, claim_b)

    contradictions = list(await asyncio.gather(*(_run(a, ca, b, cb) for a, ca, b, cb in pairs)))

    gaps = detect_research_gaps(studies)
    return ComparisonMatrix(
        clusters=clusters,
        contradictions=contradictions,
        summary=_build_summary(studies, claims, gaps),
        gaps=gaps,
    )
