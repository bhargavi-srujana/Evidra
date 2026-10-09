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

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from app.core.rate_limit import limiter
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
# Diversity caps so one big cluster / study pair cannot occupy all slots.
MAX_PAIRS_PER_CLUSTER = 4
MAX_PAIRS_PER_STUDY_PAIR = 2

_POSITIVE = {EffectDirection.INCREASES, EffectDirection.CONDITIONAL}
_NEGATIVE = {EffectDirection.DECREASES, EffectDirection.NO_EFFECT, EffectDirection.CONDITIONAL}


class CompareRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    study_ids: list[str] = Field(min_length=2, max_length=20)
    # Bounded: attacker-supplied claim lists feed O(n^2) clustering, so the
    # cap is a small multiple of the study cap above.
    claims: list[Claim] | None = Field(default=None, max_length=200)
    # Optional study records (fresh from POST /search). Supplied studies
    # cover IDs the store lacks, and cover everything when Mongo is down —
    # so /compare works off request data alone, matching search's
    # best-effort persistence instead of 503ing on a store outage.
    studies: list[Study] | None = Field(default=None, max_length=20)

    @classmethod
    def _dedupe_ids(cls, ids: list[str]) -> list[str]:
        seen: set[str] = set()
        unique: list[str] = []
        for sid in ids:
            if sid not in seen:
                seen.add(sid)
                unique.append(sid)
        return unique

    def model_post_init(self, _context: object = None) -> None:
        # Duplicate IDs would double-count total_studies and interact badly
        # with the same-study skip in _opposing_pairs: dedupe in place.
        deduped = self._dedupe_ids(list(self.study_ids))
        if len(deduped) < 2:
            raise ValueError("study_ids must contain at least 2 unique studies")
        object.__setattr__(self, "study_ids", deduped)


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


async def _fetch_studies(
    study_ids: list[str], supplied: dict[str, Study] | None = None
) -> list[Study]:
    """Resolve studies, preferring caller-supplied records.

    Supplied studies (fresh from POST /search) cover IDs the store lacks;
    Mongo backfills the rest, and supplied records win on conflict (they are
    newer than anything persisted). The store is only fatal when an ID is
    covered by neither source.
    """
    supplied_by_id = supplied or {}
    wanted = [sid for sid in study_ids if sid not in supplied_by_id]
    fetched_by_id: dict[str, Study] = {}
    if wanted:
        try:
            db = get_db()
            docs = (
                await db["studies"]
                .find({"study_id": {"$in": wanted}})
                .to_list(length=len(wanted))
            )
        except Exception as exc:
            logger.warning("Study store unavailable for compare: %s", exc)
            raise HTTPException(
                status_code=503,
                detail="Study store unavailable. Run POST /search first.",
            ) from exc
        fetched_by_id = {
            s.study_id: s for s in (_coerce_study(d) for d in docs) if s
        }
    by_id = {**fetched_by_id, **supplied_by_id}
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
        # Bound: 20 studies max × ~20 claims each; keeps the O(n²) clustering
        # bounded even when the store holds more per study.
        docs = await db["claims"].find({"study_id": {"$in": study_ids}}).to_list(length=400)
    except Exception as exc:  # noqa: BLE001 - claims optional; continue without
        logger.warning("Claim fetch skipped (store unavailable): %s", exc)
        return []
    wanted = set(study_ids)
    return [c for d in docs if (c := _coerce_claim(d)) is not None and c.study_id in wanted]


def _opposing_pairs(
    clusters_claims: list[tuple[str, list[Claim]]],
    studies_by_id: dict[str, Study],
) -> list[tuple[Study, Claim, Study, Claim]]:
    """Cross-product of opposing claims per cluster, top-ranked with diversity.

    CONDITIONAL claims pair against absolute directions (the most interesting
    "conditional vs absolute" tensions) but never against each other — two
    hedged claims are not a contradiction. NO_EFFECT pairs against INCREASES
    (effect vs no-effect), reported verbatim downstream so null vs harm are
    never conflated in prose. Selection is greedy by confidence sum with
    per-cluster and per-study-pair caps so one big cluster cannot take all
    MAX_PAIRS slots.
    """
    candidates: list[tuple[float, str, str, Study, Claim, Study, Claim]] = []
    for cluster_id, members in clusters_claims:
        positives = [c for c in members if c.effect_direction in _POSITIVE]
        negatives = [c for c in members if c.effect_direction in _NEGATIVE]
        for claim_a in positives:
            study_a = studies_by_id.get(claim_a.study_id)
            if study_a is None:
                continue
            for claim_b in negatives:
                if claim_a.study_id == claim_b.study_id:
                    continue  # same-study tension is not a contradiction
                if (
                    claim_a.effect_direction == EffectDirection.CONDITIONAL
                    and claim_b.effect_direction == EffectDirection.CONDITIONAL
                ):
                    continue  # hedged vs hedged is not a contradiction
                study_b = studies_by_id.get(claim_b.study_id)
                if study_b is None:
                    continue
                score = claim_a.confidence_score + claim_b.confidence_score
                pair_key = "|".join(sorted((claim_a.study_id, claim_b.study_id)))
                candidates.append(
                    (score, cluster_id, pair_key, study_a, claim_a, study_b, claim_b)
                )
    candidates.sort(key=lambda item: item[0], reverse=True)
    selected: list[tuple[Study, Claim, Study, Claim]] = []
    per_cluster: dict[str, int] = {}
    per_pair: dict[str, int] = {}
    for _, cluster_id, pair_key, a, ca, b, cb in candidates:
        if per_cluster.get(cluster_id, 0) >= MAX_PAIRS_PER_CLUSTER:
            continue
        if per_pair.get(pair_key, 0) >= MAX_PAIRS_PER_STUDY_PAIR:
            continue
        # Dedupe near-identical claim pairs (same two claims, either order).
        claim_key = "|".join(sorted((ca.claim_id, cb.claim_id)))
        if any(
            claim_key == "|".join(sorted((x[1].claim_id, x[3].claim_id)))
            for x in selected
        ):
            continue
        selected.append((a, ca, b, cb))
        per_cluster[cluster_id] = per_cluster.get(cluster_id, 0) + 1
        per_pair[pair_key] = per_pair.get(pair_key, 0) + 1
        if len(selected) >= MAX_PAIRS:
            break
    return selected


def _build_summary(studies: list[Study], claims: list[Claim], gaps: list[str]) -> EvidenceSummary:
    directions = [c.effect_direction for c in claims]
    return EvidenceSummary(
        total_studies=len(studies),
        positive_count=sum(1 for d in directions if d == EffectDirection.INCREASES),
        conditional_count=sum(1 for d in directions if d == EffectDirection.CONDITIONAL),
        negative_count=sum(
            1 for d in directions if d in (EffectDirection.DECREASES, EffectDirection.NO_EFFECT)
        ),
        unclear_count=sum(1 for d in directions if d == EffectDirection.UNCLEAR),
        key_gaps=gaps,
    )


@router.post("/compare", response_model=ComparisonMatrix)
@limiter.limit("20/minute")
async def compare_studies(request: Request, payload: CompareRequest) -> ComparisonMatrix:
    """Cluster claims, contrast opposing pairs, surface gaps."""
    wanted = set(payload.study_ids)
    supplied = {
        s.study_id: s for s in (payload.studies or []) if s.study_id in wanted
    }
    studies = await _fetch_studies(payload.study_ids, supplied)
    studies_by_id = {s.study_id: s for s in studies}

    if payload.claims is not None:
        claims = [c for c in payload.claims if c.study_id in studies_by_id]
    else:
        claims = await _fetch_claims(payload.study_ids)

    clusters = await cluster_claims(claims)
    claims_by_id: dict[str, Claim] = {}
    for c in claims:
        if c.claim_id in claims_by_id:
            logger.warning("Duplicate claim_id %r; keeping first occurrence", c.claim_id)
            continue
        claims_by_id[c.claim_id] = c
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
