"""Methodology-aware contradiction engine + semantic claim clustering.

Two-layer design for speed and zero-hallucination compliance:

- Deterministic core (always runs, no LLM): Jaccard-token claim clustering,
  PICO diffing with fixed impact heuristics, fact-templated observed
  differences and cautiously-worded hypotheses.
- Optional LLM polish (only when configured): one batched call to label
  cluster topics, and per-pair rephrasing strictly grounded in the supplied
  facts. Any LLM failure falls back to the deterministic output.
"""

from __future__ import annotations

import json
import logging
import re
from collections import Counter

from app.models.claim import Claim
from app.models.comparison import (
    ClaimCluster,
    MethodologicalDifference,
    PairwiseContradiction,
)
from app.models.study import Study
from app.services.common import STOPWORDS
from app.services.extraction import _chat_json, is_llm_configured

logger = logging.getLogger(__name__)

_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9\-]*")
CLUSTER_SIMILARITY_THRESHOLD = 0.22
MAX_TOPIC_WORDS = 3

# (StudyDesign field, display label, base impact when values differ)
_DIMENSIONS: tuple[tuple[str, str, str], ...] = (
    ("population", "Population", "HIGH"),
    ("task_type", "Task Type", "HIGH"),
    ("measurement_metric", "Measurement Metric", "HIGH"),
    ("intervention", "Intervention", "MEDIUM"),
    ("control", "Control Group", "MEDIUM"),
    ("study_type", "Study Type / Setting", "MEDIUM"),
    ("sample_size", "Sample Size", "LOW"),
    ("study_duration", "Study Duration", "LOW"),
)
_SAMPLE_SIZE_UPGRADE_RATIO = 10  # 10x numeric gap promotes Sample Size to MEDIUM
# Sample-size cues only (see gap_analysis): never mistake a year for N.
_SAMPLE_N_RE = re.compile(r"\b[NMnm]\s*=\s*(\d[\d,]*)")
_SAMPLE_UNIT_RE = re.compile(
    r"\b(\d[\d,]*)\s+"
    r"(participants|subjects|students|patients|volunteers|adults|children|samples?|trials)\b",
    re.IGNORECASE,
)


def _tokens(text: str) -> set[str]:
    return {
        t.strip("-")
        for t in _TOKEN_RE.findall(text.lower())
        if len(t.strip("-")) > 1 and t.strip("-") not in STOPWORDS
    }


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _keyword_topic(texts: list[str], fallback: str) -> str:
    counts = Counter(t for text in texts for t in _tokens(text))
    top = [w for w, _ in counts.most_common(MAX_TOPIC_WORDS)]
    if not top:
        return fallback
    return " ".join(w.capitalize() for w in top)


async def _label_topics_with_llm(
    clusters: list[ClaimCluster], claims_by_id: dict[str, Claim]
) -> None:
    """Single batched LLM call to name clusters; keeps keywords on failure."""
    try:
        payload = {
            "clusters": [
                {
                    "cluster_id": c.cluster_id,
                    "keywords": c.topic,
                    "sample_claims": [
                        claims_by_id[cid].text for cid in c.claim_ids[:3] if cid in claims_by_id
                    ],
                }
                for c in clusters
            ]
        }
        system = (
            "You name groups of scientific findings. Return ONLY valid JSON: "
            '{"topics": {"<cluster_id>": "<short topic label>"}}. Rules: '
            "labels <= 6 words, title case, no claim IDs or statistics, "
            "never invent content beyond the given claims."
        )
        data = await _chat_json(system, json.dumps(payload)[:4000])
        topics = data.get("topics", {}) if isinstance(data, dict) else {}
        if not isinstance(topics, dict):
            return
        for cluster in clusters:
            label = topics.get(cluster.cluster_id)
            if isinstance(label, str) and label.strip():
                cleaned = re.sub(r"\s+", " ", label.strip())[:80]
                # Enforce the prompt contract (<=6 words, no stats/IDs):
                # over-long or digit-heavy labels fall back to keywords.
                words = cleaned.split()
                if len(words) <= 6 and not re.search(r"\d{4,}|\b[cC]-?\d+\b", cleaned):
                    cluster.topic = cleaned
    except Exception as exc:  # noqa: BLE001 - keyword labels remain
        logger.info("LLM topic labeling skipped: %s", exc)


async def cluster_claims(claims: list[Claim]) -> list[ClaimCluster]:
    """Group claims into semantic topics; returns a list of ClaimCluster.

    Greedy agglomerative clustering over Jaccard token similarity
    (deterministic, dependency-free). Topics come from keyword labels,
    upgraded by one batched LLM call when configured.
    """
    if not claims:
        return []
    token_sets = [_tokens(c.text) for c in claims]
    groups: list[list[int]] = []
    for i in range(len(claims)):
        best_idx, best_sim = -1, 0.0
        for gi, members in enumerate(groups):
            sim = max(_jaccard(token_sets[i], token_sets[m]) for m in members)
            if sim > best_sim:
                best_idx, best_sim = gi, sim
        if best_idx >= 0 and best_sim >= CLUSTER_SIMILARITY_THRESHOLD:
            groups[best_idx].append(i)
        else:
            groups.append([i])

    clusters: list[ClaimCluster] = []
    for gi, members in enumerate(groups):
        member_claims = [claims[m] for m in members]
        topic = _keyword_topic([c.text for c in member_claims], fallback=f"Claim Group {gi + 1}")
        directions = [c.effect_direction for c in member_claims]
        dominant = Counter(directions).most_common(1)[0][0]
        clusters.append(
            ClaimCluster(
                cluster_id=f"cluster-{gi + 1}",
                topic=topic,
                claim_ids=[c.claim_id for c in member_claims],
                dominant_direction=dominant,
            )
        )
    if is_llm_configured() and clusters:
        await _label_topics_with_llm(clusters, {c.claim_id: c for c in claims})
    return clusters


def _parse_int(value: str | None) -> int | None:
    """Participant count from explicit sample cues, else None (never a year)."""
    if not value:
        return None
    match = _SAMPLE_N_RE.search(value)
    if match:
        try:
            return int(match.group(1).replace(",", ""))
        except ValueError:
            pass
    match = _SAMPLE_UNIT_RE.search(value)
    if match:
        try:
            return int(match.group(1).replace(",", ""))
        except ValueError:
            return None
    return None


def _diff_designs(study_a: Study, study_b: Study) -> list[MethodologicalDifference]:
    """Deterministic PICO diff; only differing dimensions are reported."""
    design_a = study_a.design.model_dump()
    design_b = study_b.design.model_dump()
    differences: list[MethodologicalDifference] = []
    for field, label, base_impact in _DIMENSIONS:
        raw_a, raw_b = design_a.get(field), design_b.get(field)
        norm_a = (raw_a or "").strip().lower() or None
        norm_b = (raw_b or "").strip().lower() or None
        if norm_a == norm_b:
            continue  # identical, or both unreported: not a difference
        impact = base_impact
        if field == "sample_size":
            num_a, num_b = _parse_int(raw_a or ""), _parse_int(raw_b or "")
            if num_a and num_b and num_a > 0 and num_b > 0:
                ratio = max(num_a, num_b) / min(num_a, num_b)
                if ratio >= _SAMPLE_SIZE_UPGRADE_RATIO:
                    impact = "MEDIUM"
        differences.append(
            MethodologicalDifference(
                dimension=label,
                study_a_value=(raw_a or "").strip() or None,
                study_b_value=(raw_b or "").strip() or None,
                impact_level=impact,  # type: ignore[arg-type]
            )
        )
    return differences


def _observed_difference(
    study_a: Study,
    claim_a: Claim,
    study_b: Study,
    claim_b: Claim,
    differences: list[MethodologicalDifference],
) -> str:
    setup = (
        "; ".join(
            f"{d.dimension}: '{d.study_a_value or 'not reported'}' vs "
            f"'{d.study_b_value or 'not reported'}'"
            for d in differences
        )
        or "their reported setups do not differ on any recorded PICO dimension"
    )
    return (
        f"Study {study_a.study_id} reports '{claim_a.effect_direction.value}' "
        f"(confidence {claim_a.confidence_score:.2f}): '{claim_a.text}' "
        f"Study {study_b.study_id} reports '{claim_b.effect_direction.value}' "
        f"(confidence {claim_b.confidence_score:.2f}): '{claim_b.text}' "
        f"Their setups differ as follows — {setup}."
    )


def _hypothesized_explanation(
    differences: list[MethodologicalDifference],
) -> str:
    if not differences:
        return (
            "No methodological differences were reported on the recorded "
            "dimensions, so no grounded hypothesis for the divergence can be "
            "offered from the retrieved evidence."
        )
    dims = ", ".join(d.dimension for d in differences[:3])
    top = differences[0]
    return (
        f"The divergence may be conditional on {dims}; for example, "
        f"{top.dimension} differs "
        f"('{top.study_a_value or 'not reported'}' vs "
        f"'{top.study_b_value or 'not reported'}'). "
        "This is a cautious hypothesis only — it is not established by the "
        "retrieved evidence."
    )


async def _refine_with_llm(
    study_a: Study,
    claim_a: Claim,
    study_b: Study,
    claim_b: Claim,
    differences: list[MethodologicalDifference],
    observed: str,
    hypothesized: str,
) -> tuple[str, str]:
    """Optional LLM rephrase grounded strictly in supplied facts."""
    try:
        facts = {
            "study_a": {
                "id": study_a.study_id,
                "claim": claim_a.text,
                "direction": claim_a.effect_direction.value,
                "design": study_a.design.model_dump(),
            },
            "study_b": {
                "id": study_b.study_id,
                "claim": claim_b.text,
                "direction": claim_b.effect_direction.value,
                "design": study_b.design.model_dump(),
            },
            "method_differences": [d.model_dump() for d in differences],
            "draft_observed_difference": observed,
            "draft_hypothesized_explanation": hypothesized,
        }
        system = (
            "You restate a research-contradiction analysis. Return ONLY valid "
            'JSON: {"observed_difference": str, "hypothesized_explanation": '
            "str}. Rules: use ONLY the supplied facts, never add dimensions, "
            "values, or causal claims beyond them; keep neutral wording; keep "
            "the hypothesis conditional ('may', 'might'); if unsure, return "
            "the drafts verbatim."
        )
        data = await _chat_json(system, json.dumps(facts)[:5000])
        if not isinstance(data, dict):
            return observed, hypothesized
        new_observed = data.get("observed_difference")
        new_hypo = data.get("hypothesized_explanation")
        if isinstance(new_observed, str) and new_observed.strip():
            observed = new_observed.strip()[:2000]
        if isinstance(new_hypo, str) and new_hypo.strip():
            hypothesized = new_hypo.strip()[:2000]
        return observed, hypothesized
    except Exception as exc:  # noqa: BLE001 - drafts remain
        logger.info("LLM contradiction refinement skipped: %s", exc)
        return observed, hypothesized


async def analyze_contradictions(
    study_a: Study, claim_a: Claim, study_b: Study, claim_b: Claim
) -> PairwiseContradiction:
    """Compare two studies' PICO designs; never raises (defaults on error)."""
    try:
        differences = _diff_designs(study_a, study_b)
        observed = _observed_difference(study_a, claim_a, study_b, claim_b, differences)
        hypothesized = _hypothesized_explanation(differences)
        if is_llm_configured():
            observed, hypothesized = await _refine_with_llm(
                study_a,
                claim_a,
                study_b,
                claim_b,
                differences,
                observed,
                hypothesized,
            )
        return PairwiseContradiction(
            study_a_id=study_a.study_id,
            study_b_id=study_b.study_id,
            observed_difference=observed,
            hypothesized_explanation=hypothesized,
            method_differences=differences,
        )
    except Exception as exc:  # noqa: BLE001 - comparison must never break compare
        logger.warning(
            "Contradiction analysis failed for %s vs %s: %s",
            study_a.study_id,
            study_b.study_id,
            exc,
        )
        return PairwiseContradiction(
            study_a_id=study_a.study_id,
            study_b_id=study_b.study_id,
            observed_difference=(
                f"Study {study_a.study_id} reports "
                f"'{claim_a.effect_direction.value}' while Study "
                f"{study_b.study_id} reports "
                f"'{claim_b.effect_direction.value}'."
            ),
            hypothesized_explanation=("No grounded hypothesis available for this pair."),
        )


__all__ = [
    "analyze_contradictions",
    "cluster_claims",
]
