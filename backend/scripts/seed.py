"""Seed MongoDB Atlas with a deterministic Evidra demo dataset.

Covers the frontend's test research questions so the UI has instant,
high-quality answers without spending LLM quota:

- studies/claims collections: sample papers with PICO designs + extracted
  claims (stable IDs via ``make_study_id``, claim IDs ``{study_id}-c{i}``).
- search_cache: full SearchResponse snapshots keyed EXACTLY like production
  (``search-v4-…`` over neutral query + polarity scope + max_results=6, the
  frontend default), so repeat searches hit instantly.
- comparisons: precomputed contradiction clusters + evidence overview
  metrics snapshot per question (analytic reference; compare recomputes
  live at request time).

Every document is validated through the app's own Pydantic models before
insert, so seeded rows always match the API schemas. Re-runs are safe:
previously seeded IDs (tracked in ``seed_meta``) are deleted first, so no
duplicate-key errors and no touching of non-seed data.

Usage:
    cd backend && uv run python scripts/seed.py

Env (MONGODB_URI wins; falls back to the backend's MONGO_URL/MONGO_DB):
    MONGODB_URI="mongodb+srv://<user>:<pass>@<cluster>/..."  # Atlas
    MONGO_DB=evidra
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import logging
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Allow `python scripts/seed.py` from backend/ (puts backend/ on sys.path).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from motor.motor_asyncio import AsyncIOMotorClient

from app.models.claim import Claim
from app.models.comparison import ComparisonMatrix
from app.models.study import Study
from app.services.extraction import make_study_id
from app.services.query_parser import parse_query

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("evidra.seed")

SEED_META_ID = "evidra-seed-v1"
STUDIES = "studies"
CLAIMS = "claims"
SEARCH_CACHE = "search_cache"
COMPARISONS = "comparisons"
SEED_META = "seed_meta"

# The frontend's default page size; cache keys scope on it, so seed for 6.
# Smaller repeat requests slice down from this entry (larger ones re-query).
MAX_RESULTS = 6


def load_dotenv(path: Path) -> None:
    """Minimal .env loader (KEY=VALUE, # comments) — never overrides real env."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("'\"")
        if key and key not in os.environ:
            os.environ[key] = value


def masked_uri(uri: str) -> str:
    """Hide the password for safe console logging."""
    try:
        scheme, _, rest = uri.partition("://")
        if "@" not in rest:
            return uri
        creds, _, host = rest.partition("@")
        user, _, _pw = creds.partition(":")
        return f"{scheme}://{user}:***@{host}"
    except Exception:  # noqa: BLE001 - logging must never crash
        return "<unparseable-uri>"


def mongo_config() -> tuple[str, str]:
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    uri = (
        os.environ.get("MONGODB_URI") or os.environ.get("MONGO_URL") or "mongodb://localhost:27017"
    )
    db_name = os.environ.get("MONGO_DB") or "evidra"
    return uri, db_name


def search_cache_key(
    neutral_query: str,
    intervention: str = "",
    outcome: str = "",
    direction: str = "unclear",
    max_results: int = MAX_RESULTS,
) -> str:
    """Mirror of routes_search._search_cache_key (search-v4 scope)."""
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
    return f"search-v4-{hashlib.sha1(scope.encode()).hexdigest()[:16]}"


def study_doc(
    title: str,
    authors: list[str],
    year: int | None,
    venue: str | None,
    abstract: str,
    design: dict[str, str],
    url: str | None = None,
) -> dict[str, Any]:
    study_id = make_study_id(title, year, None)
    return Study(
        study_id=study_id,
        title=title,
        authors=[{"name": name} for name in authors],
        year=year,
        venue=venue,
        abstract=abstract,
        url=url,
        design=design,
        is_fallback=False,
    ).model_dump()


def claim_doc(
    study_id: str,
    index: int,
    text: str,
    effect_direction: str,
    confidence_score: float,
    evidence_span: str | None = None,
    conclusion: str | None = None,
    verbatim_evidence_quote: str | None = None,
) -> dict[str, Any]:
    return Claim(
        claim_id=f"{study_id}-c{index}",
        study_id=study_id,
        text=text,
        effect_direction=effect_direction,  # type: ignore[arg-type]
        confidence_score=confidence_score,
        evidence_span=evidence_span,
        conclusion=conclusion,
        verbatim_evidence_quote=verbatim_evidence_quote,
    ).model_dump()


def build_dataset() -> tuple[list[dict], list[dict], list[dict], list[dict]]:
    """Return (studies, claims, cache_entries, comparison_docs). All validated."""
    studies: list[dict] = []
    claims: list[dict] = []
    cache_entries: list[dict] = []
    comparison_docs: list[dict] = []
    now = datetime.now(UTC)

    questions: list[dict[str, Any]] = [
        {
            "query": "Do explanations improve trust in AI decisions?",
            "papers": [
                {
                    "title": "Why explanations improve human trust in algorithmic decisions",
                    "authors": ["Vivian Lai", "Chenhao Tan"],
                    "year": 2019,
                    "venue": "ACM CHI Workshop on Human-Centered AI",
                    "abstract": (
                        "Participants shown feature-based explanations trusted the "
                        "model's decisions significantly more than participants shown "
                        "predictions alone, and followed correct advice more often."
                    ),
                    "design": {
                        "population": "adult crowdworkers",
                        "sample_size": "n=320",
                        "intervention": "feature-based explanations",
                        "control": "predictions without explanations",
                        "task_type": "deception detection",
                        "measurement_metric": "self-reported trust rating",
                        "study_duration": "single session",
                        "study_type": "randomized experiment",
                    },
                    "claims": [
                        {
                            "text": "Feature-based explanations increase user trust in AI decisions.",
                            "effect_direction": "increases",
                            "confidence_score": 0.85,
                            "conclusion": "Explanations raised trust relative to predictions alone.",
                            "verbatim_evidence_quote": "trusted the model's decisions significantly more than participants shown predictions alone",
                        },
                    ],
                },
                {
                    "title": "Show me the numbers: quantitative explanations raise reliance on AI advice",
                    "authors": ["Maya Lindqvist", "Jonas Weber"],
                    "year": 2021,
                    "venue": "FAccT",
                    "abstract": (
                        "Across two preregistered experiments, quantitative explanations "
                        "raised self-reported trust and appropriate reliance on AI advice "
                        "compared with a no-explanation baseline."
                    ),
                    "design": {
                        "population": "adult online participants",
                        "sample_size": "n=512",
                        "intervention": "quantitative explanations",
                        "control": "no-explanation baseline",
                        "task_type": "loan approval review",
                        "measurement_metric": "trust questionnaire and advice uptake",
                        "study_duration": "two sessions",
                        "study_type": "preregistered randomized experiment",
                    },
                    "claims": [
                        {
                            "text": "Quantitative explanations increase trust and appropriate reliance on AI advice.",
                            "effect_direction": "increases",
                            "confidence_score": 0.78,
                            "conclusion": "Explanations beat the no-explanation baseline on trust and uptake.",
                            "verbatim_evidence_quote": "raised self-reported trust and appropriate reliance on AI advice compared with a no-explanation baseline",
                        },
                    ],
                },
                {
                    "title": "Explanations do not raise trust when model accuracy is low",
                    "authors": ["Priya Natarajan", "Tom Okafor"],
                    "year": 2022,
                    "venue": "IUI",
                    "abstract": (
                        "When the underlying model was inaccurate, explanations produced "
                        "no significant change in trust relative to the baseline; "
                        "participants discounted both advice and rationale."
                    ),
                    "design": {
                        "population": "adult crowdworkers",
                        "sample_size": "n=210",
                        "intervention": "feature-based explanations",
                        "control": "predictions without explanations",
                        "task_type": "income prediction review",
                        "measurement_metric": "trust rating",
                        "study_duration": "single session",
                        "study_type": "randomized experiment with low-accuracy model",
                    },
                    "claims": [
                        {
                            "text": "Explanations show no effect on trust when the model is inaccurate.",
                            "effect_direction": "no_effect",
                            "confidence_score": 0.71,
                            "conclusion": "No significant trust change under low model accuracy.",
                            "verbatim_evidence_quote": "no significant change in trust relative to the baseline",
                        },
                    ],
                },
                {
                    "title": "Counterfactual explanations improve appropriate reliance on AI advice",
                    "authors": ["Helen Zhang", "Mark Lim"],
                    "year": 2023,
                    "venue": "CHI",
                    "abstract": (
                        "Participants given counterfactual explanations followed correct "
                        "AI advice more often and overrode incorrect advice more often "
                        "than participants shown only predictions, raising appropriate reliance."
                    ),
                    "design": {
                        "population": "adult online participants",
                        "sample_size": "n=428",
                        "intervention": "counterfactual explanations",
                        "control": "predictions without explanations",
                        "task_type": "medical diagnosis review",
                        "measurement_metric": "advice agreement and trust",
                        "study_duration": "single session",
                        "study_type": "randomized experiment",
                    },
                    "claims": [
                        {
                            "text": "Counterfactual explanations increase appropriate reliance on AI advice.",
                            "effect_direction": "increases",
                            "confidence_score": 0.76,
                            "conclusion": "Counterfactuals improved both uptake of good advice and rejection of bad advice.",
                            "verbatim_evidence_quote": "followed correct AI advice more often and overrode incorrect advice more often",
                        },
                    ],
                },
                {
                    "title": "Explanations improve trust mainly for users with high AI literacy",
                    "authors": ["Ingrid Halvorsen", "Pablo Mendez"],
                    "year": 2022,
                    "venue": "CSCW",
                    "abstract": (
                        "Explanations raised trust substantially for participants with high "
                        "AI literacy, while participants with low AI literacy showed little "
                        "change, indicating the benefit depends on audience expertise."
                    ),
                    "design": {
                        "population": "adults with mixed AI literacy",
                        "sample_size": "n=350",
                        "intervention": "plain-language explanations",
                        "control": "no explanations",
                        "task_type": "hiring screening review",
                        "measurement_metric": "trust rating by literacy subgroup",
                        "study_duration": "single session",
                        "study_type": "quasi-experimental survey",
                    },
                    "claims": [
                        {
                            "text": "Explanations improve trust conditional on high user AI literacy.",
                            "effect_direction": "conditional",
                            "confidence_score": 0.67,
                            "conclusion": "Trust gains concentrate among AI-literate users.",
                            "verbatim_evidence_quote": "raised trust substantially for participants with high AI literacy",
                        },
                    ],
                },
                {
                    "title": "Revealing model errors through explanations reduces user trust",
                    "authors": ["Aisha Bello", "Ruben Garcia"],
                    "year": 2024,
                    "venue": "FAccT",
                    "abstract": (
                        "When explanations exposed the model's reliance on spurious features, "
                        "participants trusted the system significantly less than participants "
                        "who saw predictions alone."
                    ),
                    "design": {
                        "population": "adult crowdworkers",
                        "sample_size": "n=275",
                        "intervention": "error-revealing explanations",
                        "control": "predictions without explanations",
                        "task_type": "toxicity classification review",
                        "measurement_metric": "trust rating",
                        "study_duration": "single session",
                        "study_type": "randomized experiment",
                    },
                    "claims": [
                        {
                            "text": "Error-revealing explanations decrease user trust in the system.",
                            "effect_direction": "decreases",
                            "confidence_score": 0.64,
                            "conclusion": "Transparency about flaws lowered trust.",
                            "verbatim_evidence_quote": "trusted the system significantly less than participants who saw predictions alone",
                        },
                    ],
                },
            ],
        },
        {
            "query": "Does sleep improve memory consolidation?",
            "papers": [
                {
                    "title": "Sleep benefits memory consolidation: a targeted review",
                    "authors": ["Susan Diekelmann", "Jan Born"],
                    "year": 2010,
                    "venue": "Nature Reviews Neuroscience",
                    "abstract": (
                        "Converging behavioral and physiological evidence indicates that "
                        "sleep actively consolidates memories, with slow-wave sleep "
                        "supporting declarative memory."
                    ),
                    "design": {
                        "population": "healthy adults",
                        "sample_size": "review of 30 studies",
                        "intervention": "post-learning sleep",
                        "control": "equivalent wake retention interval",
                        "task_type": "declarative memory recall",
                        "measurement_metric": "recall accuracy",
                        "study_duration": "overnight retention",
                        "study_type": "targeted review",
                    },
                    "claims": [
                        {
                            "text": "Post-learning sleep improves declarative memory consolidation.",
                            "effect_direction": "increases",
                            "confidence_score": 0.88,
                            "conclusion": "Sleep actively consolidates declarative memories.",
                            "verbatim_evidence_quote": "sleep actively consolidates memories, with slow-wave sleep supporting declarative memory",
                        },
                    ],
                },
                {
                    "title": "REM sleep and emotional memory: effects depend on sleep stage",
                    "authors": ["Elena Fischer", "David Adeyemi"],
                    "year": 2016,
                    "venue": "Sleep",
                    "abstract": (
                        "Emotional memory consolidation improved only when retention "
                        "included sufficient REM sleep; neutral material showed no "
                        "such dependency."
                    ),
                    "design": {
                        "population": "healthy young adults",
                        "sample_size": "n=96",
                        "intervention": "REM-rich sleep",
                        "control": "REM-deprived sleep",
                        "task_type": "emotional picture recognition",
                        "measurement_metric": "recognition accuracy",
                        "study_duration": "overnight retention",
                        "study_type": "sleep laboratory experiment",
                    },
                    "claims": [
                        {
                            "text": "Sleep improves emotional memory consolidation conditional on sufficient REM sleep.",
                            "effect_direction": "conditional",
                            "confidence_score": 0.66,
                            "conclusion": "Benefit holds for emotional material with REM-rich sleep only.",
                            "verbatim_evidence_quote": "improved only when retention included sufficient REM sleep",
                        },
                    ],
                },
                {
                    "title": "No sleep benefit for procedural learning at short retention intervals",
                    "authors": ["Kenji Mori", "Anna Svensson"],
                    "year": 2018,
                    "venue": "Journal of Sleep Research",
                    "abstract": (
                        "A finger-tapping procedural task showed no significant "
                        "difference between sleep and wake groups after a 12-hour "
                        "retention interval."
                    ),
                    "design": {
                        "population": "healthy adults",
                        "sample_size": "n=140",
                        "intervention": "12-hour interval with sleep",
                        "control": "12-hour interval awake",
                        "task_type": "finger-tapping procedural task",
                        "measurement_metric": "speed and accuracy",
                        "study_duration": "12-hour retention",
                        "study_type": "randomized experiment",
                    },
                    "claims": [
                        {
                            "text": "Sleep shows no effect on procedural learning at a 12-hour interval.",
                            "effect_direction": "no_effect",
                            "confidence_score": 0.62,
                            "conclusion": "No significant sleep-wake difference for this task and interval.",
                            "verbatim_evidence_quote": "no significant difference between sleep and wake groups after a 12-hour retention interval",
                        },
                    ],
                },
                {
                    "title": "Targeted memory reactivation during slow-wave sleep strengthens consolidation",
                    "authors": ["Bjorn Eriksen", "Clara Novak"],
                    "year": 2017,
                    "venue": "Neuron",
                    "abstract": (
                        "Cues replayed during slow-wave sleep strengthened later recall "
                        "significantly compared with uncued items, confirming an active "
                        "consolidation role for sleep."
                    ),
                    "design": {
                        "population": "healthy adults",
                        "sample_size": "n=60",
                        "intervention": "auditory cue replay during slow-wave sleep",
                        "control": "uncued items",
                        "task_type": "vocabulary recall",
                        "measurement_metric": "recall accuracy",
                        "study_duration": "sleep laboratory night",
                        "study_type": "within-subject experiment",
                    },
                    "claims": [
                        {
                            "text": "Cue replay during slow-wave sleep improves later recall.",
                            "effect_direction": "increases",
                            "confidence_score": 0.81,
                            "conclusion": "Targeted reactivation confirms sleep's active consolidation role.",
                            "verbatim_evidence_quote": "strengthened later recall significantly compared with uncued items",
                        },
                    ],
                },
                {
                    "title": "Daytime naps benefit memory only in habitual nappers",
                    "authors": ["Fatima Alami", "Peter Lund"],
                    "year": 2019,
                    "venue": "Sleep Medicine",
                    "abstract": (
                        "A 90-minute nap improved word-pair retention in habitual nappers, "
                        "while non-nappers showed no reliable gain over wakefulness."
                    ),
                    "design": {
                        "population": "young adults grouped by napping habit",
                        "sample_size": "n=88",
                        "intervention": "90-minute nap",
                        "control": "equivalent wake interval",
                        "task_type": "word-pair learning",
                        "measurement_metric": "retention score",
                        "study_duration": "single day",
                        "study_type": "quasi-experiment",
                    },
                    "claims": [
                        {
                            "text": "Daytime naps improve retention conditional on habitual napping.",
                            "effect_direction": "conditional",
                            "confidence_score": 0.64,
                            "conclusion": "Nap benefits concentrate among habitual nappers.",
                            "verbatim_evidence_quote": "improved word-pair retention in habitual nappers",
                        },
                    ],
                },
                {
                    "title": "Sleep shows no advantage for recognition of familiar faces",
                    "authors": ["Hana Sato", "Erik Johansson"],
                    "year": 2020,
                    "venue": "Memory",
                    "abstract": (
                        "Recognition accuracy for previously seen faces did not differ "
                        "significantly between the sleep and wake groups."
                    ),
                    "design": {
                        "population": "healthy adults",
                        "sample_size": "n=120",
                        "intervention": "overnight sleep",
                        "control": "daytime wake interval",
                        "task_type": "face recognition",
                        "measurement_metric": "recognition accuracy",
                        "study_duration": "12-hour retention",
                        "study_type": "randomized experiment",
                    },
                    "claims": [
                        {
                            "text": "Sleep shows no effect on familiar face recognition.",
                            "effect_direction": "no_effect",
                            "confidence_score": 0.6,
                            "conclusion": "No sleep advantage for this recognition task.",
                            "verbatim_evidence_quote": "did not differ significantly between the sleep and wake groups",
                        },
                    ],
                },
            ],
        },
        {
            "query": "Does spaced repetition beat massed practice?",
            "papers": [
                {
                    "title": "Spacing effects in learning: a temporal ridgeline of optimal retention",
                    "authors": [
                        "Nicholas Cepeda",
                        "Harold Pashler",
                        "Edward Vul",
                        "John Wixted",
                        "Sean Rohrer",
                    ],
                    "year": 2006,
                    "venue": "Psychological Science",
                    "abstract": (
                        "Across two large experiments, spaced study produced substantially "
                        "better long-term recall than massed study, with optimal gaps "
                        "widening as the retention interval grew."
                    ),
                    "design": {
                        "population": "university students and online adults",
                        "sample_size": "n=1354",
                        "intervention": "spaced restudy",
                        "control": "massed restudy",
                        "task_type": "general-knowledge recall",
                        "measurement_metric": "recall accuracy",
                        "study_duration": "up to 6-month retention",
                        "study_type": "two large experiments",
                    },
                    "claims": [
                        {
                            "text": "Spaced study improves long-term recall over massed study.",
                            "effect_direction": "increases",
                            "confidence_score": 0.87,
                            "conclusion": "Spacing beats massing, with wider gaps for longer intervals.",
                            "verbatim_evidence_quote": "spaced study produced substantially better long-term recall than massed study",
                        },
                    ],
                },
                {
                    "title": "The critical importance of retrieval for learning",
                    "authors": ["Jeffrey Karpicke", "Henry Roediger"],
                    "year": 2008,
                    "venue": "Science",
                    "abstract": (
                        "Repeated retrieval practice produced greater long-term retention "
                        "than repeated restudying, even though restudying felt more "
                        "effective to learners."
                    ),
                    "design": {
                        "population": "undergraduates",
                        "sample_size": "n=120",
                        "intervention": "repeated retrieval practice",
                        "control": "repeated restudy",
                        "task_type": "foreign-language vocabulary",
                        "measurement_metric": "cued recall",
                        "study_duration": "one-week retention",
                        "study_type": "laboratory experiment",
                    },
                    "claims": [
                        {
                            "text": "Retrieval practice improves long-term retention over restudying.",
                            "effect_direction": "increases",
                            "confidence_score": 0.82,
                            "conclusion": "Testing beats restudying despite learners' intuitions.",
                            "verbatim_evidence_quote": "Repeated retrieval practice produced greater long-term retention than repeated restudying",
                        },
                    ],
                },
                {
                    "title": "Spaced retrieval beats massed review in middle-school science classes",
                    "authors": ["Marta Kowalski", "David Chen"],
                    "year": 2019,
                    "venue": "Journal of Educational Psychology",
                    "abstract": (
                        "Students using spaced retrieval scored markedly higher on delayed "
                        "unit tests than students using massed review sessions."
                    ),
                    "design": {
                        "population": "middle-school students",
                        "sample_size": "n=340",
                        "intervention": "spaced retrieval quizzes",
                        "control": "massed review sessions",
                        "task_type": "science unit tests",
                        "measurement_metric": "delayed test scores",
                        "study_duration": "one-semester course",
                        "study_type": "classroom randomized trial",
                    },
                    "claims": [
                        {
                            "text": "Spaced retrieval improves delayed classroom test scores over massed review.",
                            "effect_direction": "increases",
                            "confidence_score": 0.8,
                            "conclusion": "Spacing advantage replicates in real classrooms.",
                            "verbatim_evidence_quote": "scored markedly higher on delayed unit tests than students using massed review sessions",
                        },
                    ],
                },
                {
                    "title": "Expanding retrieval schedules help only when initial recall succeeds",
                    "authors": ["Anette Schmidt", "Lars Johansson"],
                    "year": 2017,
                    "venue": "Memory & Cognition",
                    "abstract": (
                        "Expanding spaced schedules improved retention over uniform schedules "
                        "only when learners recalled successfully on the first attempt; "
                        "failed first attempts erased the advantage."
                    ),
                    "design": {
                        "population": "university students",
                        "sample_size": "n=180",
                        "intervention": "expanding retrieval schedule",
                        "control": "uniform spaced schedule",
                        "task_type": "paired-associate learning",
                        "measurement_metric": "final recall",
                        "study_duration": "two-day retention",
                        "study_type": "laboratory experiment",
                    },
                    "claims": [
                        {
                            "text": "Expanding schedules improve retention conditional on successful first recall.",
                            "effect_direction": "conditional",
                            "confidence_score": 0.68,
                            "conclusion": "Schedule benefits depend on initial retrieval success.",
                            "verbatim_evidence_quote": "improved retention over uniform schedules only when learners recalled successfully on the first attempt",
                        },
                    ],
                },
                {
                    "title": "Massed cramming matches spacing on immediate tests",
                    "authors": ["Ravi Patel", "Grace Kim"],
                    "year": 2021,
                    "venue": "Scholarship of Teaching and Learning",
                    "abstract": (
                        "On a test given five minutes after study, massed crammers performed "
                        "no worse than spaced learners; the spacing advantage emerged only "
                        "after a delay."
                    ),
                    "design": {
                        "population": "undergraduates",
                        "sample_size": "n=150",
                        "intervention": "spaced study",
                        "control": "massed cramming",
                        "task_type": "psychology definitions test",
                        "measurement_metric": "immediate test score",
                        "study_duration": "5-minute retention",
                        "study_type": "randomized experiment",
                    },
                    "claims": [
                        {
                            "text": "Spacing shows no effect on immediate tests versus cramming.",
                            "effect_direction": "no_effect",
                            "confidence_score": 0.6,
                            "conclusion": "Spacing advantage needs a retention delay to appear.",
                            "verbatim_evidence_quote": "massed crammers performed no worse than spaced learners",
                        },
                    ],
                },
                {
                    "title": "A meta-analysis of the spacing effect in applied settings",
                    "authors": ["Feng Liu", "Olivia Brown", "Samuel Davis"],
                    "year": 2023,
                    "venue": "Review of Educational Research",
                    "abstract": (
                        "Across 89 applied studies, spaced practice outperformed massed "
                        "practice with a medium-to-large average effect."
                    ),
                    "design": {
                        "population": "varied learner samples",
                        "sample_size": "k=89 studies",
                        "intervention": "spaced practice",
                        "control": "massed practice",
                        "task_type": "mixed academic tasks",
                        "measurement_metric": "standardized learning gain",
                        "study_duration": "varied retention intervals",
                        "study_type": "meta-analysis",
                    },
                    "claims": [
                        {
                            "text": "Meta-analytic evidence favors spaced over massed practice.",
                            "effect_direction": "increases",
                            "confidence_score": 0.75,
                            "conclusion": "Medium-to-large average spacing advantage across applied studies.",
                            "verbatim_evidence_quote": "spaced practice outperformed massed practice with a medium-to-large average effect",
                        },
                    ],
                },
            ],
        },
        {
            "query": "Do LLMs reduce cognitive load in tutoring?",
            "papers": [
                {
                    "title": "LLM-generated hints lower extraneous cognitive load in algebra tutoring",
                    "authors": ["Hannah Cole", "Ibrahim Yusuf"],
                    "year": 2024,
                    "venue": "AIED",
                    "abstract": (
                        "Students receiving LLM-generated step hints reported significantly "
                        "lower extraneous cognitive load and solved more problems than "
                        "students with static textbook hints."
                    ),
                    "design": {
                        "population": "high-school students",
                        "sample_size": "n=240",
                        "intervention": "LLM-generated step hints",
                        "control": "static textbook hints",
                        "task_type": "algebra problem solving",
                        "measurement_metric": "NASA-TLX load scores and completion",
                        "study_duration": "four-week unit",
                        "study_type": "randomized classroom trial",
                    },
                    "claims": [
                        {
                            "text": "LLM hints reduce extraneous cognitive load in algebra tutoring.",
                            "effect_direction": "increases",
                            "confidence_score": 0.8,
                            "conclusion": "LLM hints lowered load and raised completion over static hints.",
                            "verbatim_evidence_quote": "reported significantly lower extraneous cognitive load and solved more problems",
                        },
                    ],
                },
                {
                    "title": "Worked examples from LLMs ease problem-solving load for novices",
                    "authors": ["Sofia Marino", "Ken Watanabe"],
                    "year": 2023,
                    "venue": "Computers & Education",
                    "abstract": (
                        "Novice programmers studying LLM-produced worked examples experienced "
                        "lower mental effort and higher post-test scores than those solving unaided."
                    ),
                    "design": {
                        "population": "novice programmers",
                        "sample_size": "n=175",
                        "intervention": "LLM worked examples",
                        "control": "unaided problem solving",
                        "task_type": "introductory Python tasks",
                        "measurement_metric": "mental-effort ratings and post-test",
                        "study_duration": "two-week module",
                        "study_type": "quasi-experiment",
                    },
                    "claims": [
                        {
                            "text": "LLM worked examples reduce mental effort for novice programmers.",
                            "effect_direction": "increases",
                            "confidence_score": 0.74,
                            "conclusion": "Worked examples lowered effort and raised scores.",
                            "verbatim_evidence_quote": "experienced lower mental effort and higher post-test scores than those solving unaided",
                        },
                    ],
                },
                {
                    "title": "The expertise reversal effect in LLM tutoring: novices gain, experts stall",
                    "authors": ["Daniel Osei", "Nina Petrova"],
                    "year": 2024,
                    "venue": "Learning and Instruction",
                    "abstract": (
                        "LLM tutoring reduced cognitive load for novices but left expert "
                        "learners unaffected, consistent with an expertise reversal effect."
                    ),
                    "design": {
                        "population": "mixed-expertise learners",
                        "sample_size": "n=310",
                        "intervention": "LLM tutor",
                        "control": "human-designed materials",
                        "task_type": "physics problem solving",
                        "measurement_metric": "cognitive-load scales by expertise",
                        "study_duration": "three-week module",
                        "study_type": "randomized trial with expertise split",
                    },
                    "claims": [
                        {
                            "text": "LLM tutoring reduces load conditional on learner novice status.",
                            "effect_direction": "conditional",
                            "confidence_score": 0.69,
                            "conclusion": "Load benefits concentrate among novices.",
                            "verbatim_evidence_quote": "reduced cognitive load for novices but left expert learners unaffected",
                        },
                    ],
                },
                {
                    "title": "LLM tutors match but do not beat human tutors on cognitive load",
                    "authors": ["Laura Bennett", "Marcus Reid"],
                    "year": 2024,
                    "venue": "British Journal of Educational Technology",
                    "abstract": (
                        "Self-reported cognitive load did not differ significantly between "
                        "students tutored by an LLM and those tutored by experienced humans."
                    ),
                    "design": {
                        "population": "undergraduates",
                        "sample_size": "n=200",
                        "intervention": "LLM tutor",
                        "control": "experienced human tutors",
                        "task_type": "statistics tutoring",
                        "measurement_metric": "self-reported cognitive load",
                        "study_duration": "single session",
                        "study_type": "randomized experiment",
                    },
                    "claims": [
                        {
                            "text": "LLM tutoring shows no load advantage over human tutoring.",
                            "effect_direction": "no_effect",
                            "confidence_score": 0.63,
                            "conclusion": "No significant load difference between tutor types.",
                            "verbatim_evidence_quote": "did not differ significantly between students tutored by an LLM and those tutored by experienced humans",
                        },
                    ],
                },
                {
                    "title": "Verbose LLM explanations raise extraneous load in tutoring dialogues",
                    "authors": ["Yuki Tanaka", "Omar Haddad"],
                    "year": 2025,
                    "venue": "LAK",
                    "abstract": (
                        "Long, verbose LLM explanations increased extraneous cognitive load "
                        "compared with concise tutor messages, hurting task performance."
                    ),
                    "design": {
                        "population": "adult learners",
                        "sample_size": "n=190",
                        "intervention": "verbose LLM explanations",
                        "control": "concise tutor messages",
                        "task_type": "data-literacy tutoring",
                        "measurement_metric": "extraneous-load subscale and accuracy",
                        "study_duration": "single session",
                        "study_type": "randomized experiment",
                    },
                    "claims": [
                        {
                            "text": "Verbose LLM explanations increase extraneous cognitive load.",
                            "effect_direction": "decreases",
                            "confidence_score": 0.66,
                            "conclusion": "Verbosity raised load and hurt performance.",
                            "verbatim_evidence_quote": "increased extraneous cognitive load compared with concise tutor messages",
                        },
                    ],
                },
                {
                    "title": "On-demand LLM help trims load; proactive interruptions add it back",
                    "authors": ["Clara Dubois", "Felix Meyer"],
                    "year": 2025,
                    "venue": "IJAIED",
                    "abstract": (
                        "Learners who requested LLM help on demand reported lower load, while "
                        "learners receiving proactive LLM interruptions reported higher load "
                        "than controls."
                    ),
                    "design": {
                        "population": "university students",
                        "sample_size": "n=225",
                        "intervention": "on-demand LLM help",
                        "control": "proactive LLM interruptions",
                        "task_type": "essay revision",
                        "measurement_metric": "load ratings",
                        "study_duration": "two sessions",
                        "study_type": "randomized experiment",
                    },
                    "claims": [
                        {
                            "text": "On-demand LLM help reduces load, unlike proactive interruptions.",
                            "effect_direction": "conditional",
                            "confidence_score": 0.61,
                            "conclusion": "Delivery mode decides whether LLMs trim or add load.",
                            "verbatim_evidence_quote": "requested LLM help on demand reported lower load",
                        },
                    ],
                },
            ],
        },
    ]

    for q in questions:
        q_studies: list[dict] = []
        q_claims: list[dict] = []
        for paper in q["papers"]:
            s = study_doc(
                title=paper["title"],
                authors=paper["authors"],
                year=paper["year"],
                venue=paper["venue"],
                abstract=paper["abstract"],
                design=paper["design"],
            )
            q_studies.append(s)
            for i, c in enumerate(paper["claims"], start=1):
                q_claims.append(
                    claim_doc(
                        study_id=s["study_id"],
                        index=i,
                        text=c["text"],
                        effect_direction=c["effect_direction"],
                        confidence_score=c["confidence_score"],
                        conclusion=c.get("conclusion"),
                        verbatim_evidence_quote=c.get("verbatim_evidence_quote"),
                    )
                )

        parsed = parse_query(q["query"])
        key = search_cache_key(
            parsed.neutral_search_query,
            parsed.intervention,
            parsed.outcome,
            parsed.expected_direction,
            MAX_RESULTS,
        )
        cache_entries.append(
            {
                "key": key,
                "neutral_query": parsed.neutral_search_query,
                "query": q["query"],
                "results": q_studies,
                "claims": q_claims,
                "intervention": parsed.intervention,
                "outcome": parsed.outcome,
                "expected_direction": parsed.expected_direction,
                "anchor_question": parsed.anchor_question,
                "warnings": [],
                "created_at": now,
                "updated_at": now,
            }
        )

        # Evidence overview metrics derived from the seeded claims.
        direction_counts = {
            "increases": 0,
            "conditional": 0,
            "decreases": 0,
            "no_effect": 0,
            "unclear": 0,
        }
        for c in q_claims:
            direction_counts[c["effect_direction"]] = (
                direction_counts.get(c["effect_direction"], 0) + 1
            )
        cluster_id = f"cluster-{key[-8:]}"
        # Opposing pair: lead study vs the first study whose top claim
        # genuinely differs in direction (falls back to the last study).
        opp_idx = next(
            (
                j
                for j in range(1, len(q_claims))
                if q_claims[j]["effect_direction"] != q_claims[0]["effect_direction"]
            ),
            len(q_studies) - 1,
        )
        matrix = ComparisonMatrix(
            clusters=[
                {
                    "cluster_id": cluster_id,
                    "topic": f"{parsed.outcome or parsed.neutral_search_query} under {parsed.intervention or 'studied conditions'}",
                    "claim_ids": [c["claim_id"] for c in q_claims],
                    "dominant_direction": max(q_claims, key=lambda c: c["confidence_score"])[
                        "effect_direction"
                    ],
                }
            ],
            contradictions=[
                {
                    "study_a_id": q_studies[0]["study_id"],
                    "study_b_id": q_studies[opp_idx]["study_id"],
                    "observed_difference": (
                        f"Study 1 reports {q_claims[0]['effect_direction']} while "
                        f"study {opp_idx + 1} reports "
                        f"{q_claims[opp_idx]['effect_direction']} "
                        f"for the same question."
                    ),
                    "hypothesized_explanation": (
                        "Methodological differences (population, task, and "
                        "conditions) likely moderate the effect."
                    ),
                    "method_differences": [
                        {
                            "dimension": "task_type",
                            "study_a_value": q_studies[0]["design"].get("task_type"),
                            "study_b_value": q_studies[opp_idx]["design"].get("task_type"),
                            "impact_level": "HIGH",
                        },
                        {
                            "dimension": "sample_size",
                            "study_a_value": q_studies[0]["design"].get("sample_size"),
                            "study_b_value": q_studies[opp_idx]["design"].get("sample_size"),
                            "impact_level": "MEDIUM",
                        },
                    ],
                }
            ],
            summary={
                "total_studies": len(q_studies),
                "positive_count": direction_counts.get("increases", 0),
                "conditional_count": direction_counts.get("conditional", 0),
                "negative_count": direction_counts.get("decreases", 0)
                + direction_counts.get("no_effect", 0),
                "unclear_count": direction_counts.get("unclear", 0),
                "key_gaps": [
                    "Long-term retention intervals are under-reported.",
                    "Sample diversity beyond crowdworker populations is thin.",
                ],
            },
            gaps=[
                "Long-term retention intervals are under-reported.",
                "Sample diversity beyond crowdworker populations is thin.",
            ],
        ).model_dump()
        comparison_docs.append(
            {
                "key": f"comparison-v1-{key}",
                "query": q["query"],
                "matrix": matrix,
                "created_at": now,
                "updated_at": now,
            }
        )

        studies.extend(q_studies)
        claims.extend(q_claims)

    # Cache-coherence guard (mirrors routes_search): every study needs a
    # claim, and at least one claim must carry real (≥0.5) confidence.
    claimed = {c["study_id"] for c in claims}
    assert all(s["study_id"] in claimed for s in studies), "seed studies without claims"
    assert any(c["confidence_score"] >= 0.5 for c in claims), "seed claims lack signal"
    assert all(not s["is_fallback"] for s in studies), "seed studies must not be fallback"
    return studies, claims, cache_entries, comparison_docs


async def main() -> int:
    uri, db_name = mongo_config()
    logger.info("Connecting to MongoDB at %s (db=%s)", masked_uri(uri), db_name)
    client = AsyncIOMotorClient(uri, serverSelectionTimeoutMS=10000)
    try:
        await client.admin.command("ping")
    except Exception as exc:  # noqa: BLE001 - any driver error means unreachable
        logger.error("MongoDB connection failed: %s", exc)
        logger.error("Set MONGODB_URI (Atlas) or MONGO_URL and retry.")
        return 1
    logger.info("MongoDB connection OK")
    db = client[db_name]

    studies, claims, cache_entries, comparison_docs = build_dataset()
    study_ids = [s["study_id"] for s in studies]
    claim_ids = [c["claim_id"] for c in claims]
    cache_keys = [e["key"] for e in cache_entries]
    comparison_keys = [d["key"] for d in comparison_docs]

    # Cleanup: remove only previously seeded rows (tracked in seed_meta),
    # so re-runs never hit duplicate-key errors and live data is untouched.
    try:
        meta = await db[SEED_META].find_one({"_id": SEED_META_ID})
    except Exception as exc:  # noqa: BLE001 - metadata read is best-effort
        logger.error("Failed to read seed metadata: %s", exc)
        return 1
    if meta:
        logger.info("Removing previous seed dataset...")
        del_studies = await db[STUDIES].delete_many(
            {"study_id": {"$in": meta.get("study_ids", [])}}
        )
        del_claims = await db[CLAIMS].delete_many({"claim_id": {"$in": meta.get("claim_ids", [])}})
        del_cache = await db[SEARCH_CACHE].delete_many({"key": {"$in": meta.get("cache_keys", [])}})
        del_comp = await db[COMPARISONS].delete_many(
            {"key": {"$in": meta.get("comparison_keys", [])}}
        )
        logger.info(
            "Cleanup removed %d studies, %d claims, %d cache entries, %d comparisons",
            del_studies.deleted_count,
            del_claims.deleted_count,
            del_cache.deleted_count,
            del_comp.deleted_count,
        )
    else:
        logger.info("No previous seed found; fresh insert")

    try:
        # Defensive: also clear any rows colliding with the incoming IDs
        # (covers seeds written before seed_meta existed).
        await db[STUDIES].delete_many({"study_id": {"$in": study_ids}})
        await db[CLAIMS].delete_many({"claim_id": {"$in": claim_ids}})
        await db[SEARCH_CACHE].delete_many({"key": {"$in": cache_keys}})
        await db[COMPARISONS].delete_many({"key": {"$in": comparison_keys}})

        # Deep-copy: insert_many mutates dicts in place (adds _id), which
        # would otherwise leak _id into the nested results/claims snapshots
        # and break strict re-validation on read-back.
        ins_studies = await db[STUDIES].insert_many(copy.deepcopy(studies))
        ins_claims = await db[CLAIMS].insert_many(copy.deepcopy(claims))
        ins_cache = await db[SEARCH_CACHE].insert_many(copy.deepcopy(cache_entries))
        ins_comp = await db[COMPARISONS].insert_many(copy.deepcopy(comparison_docs))
        await db[SEED_META].update_one(
            {"_id": SEED_META_ID},
            {
                "$set": {
                    "study_ids": study_ids,
                    "claim_ids": claim_ids,
                    "cache_keys": cache_keys,
                    "comparison_keys": comparison_keys,
                    "seeded_at": datetime.now(UTC),
                }
            },
            upsert=True,
        )
        # Idempotent unique indexes (match app ensure_indexes).
        await db[STUDIES].create_index("study_id", unique=True)
        await db[CLAIMS].create_index("claim_id", unique=True)
        await db[CLAIMS].create_index("study_id")
        await db[SEARCH_CACHE].create_index("key", unique=True)
        await db[COMPARISONS].create_index("key", unique=True)
    except Exception as exc:  # noqa: BLE001 - report insert/index failure, exit 1
        logger.error("Seed insert failed: %s", exc)
        return 1
    logger.info(
        "Inserted %d studies, %d claims, %d cache entries, %d comparisons",
        len(ins_studies.inserted_ids),
        len(ins_claims.inserted_ids),
        len(ins_cache.inserted_ids),
        len(ins_comp.inserted_ids),
    )

    # Verification: read back and re-validate through the API schemas.
    try:
        n_studies = await db[STUDIES].count_documents({"study_id": {"$in": study_ids}})
        n_claims = await db[CLAIMS].count_documents({"claim_id": {"$in": claim_ids}})
        sample = await db[SEARCH_CACHE].find_one({"key": cache_keys[0]})
        assert sample is not None, "seeded cache entry missing on read-back"
        sample.pop("_id", None)  # Mongo-internal field, not part of the schema
        _ = [Study(**item) for item in sample["results"]]
        _ = [Claim(**item) for item in sample["claims"]]
        logger.info(
            "Verified %d/%d studies, %d/%d claims; cache entry '%s' re-validates",
            n_studies,
            len(study_ids),
            n_claims,
            len(claim_ids),
            cache_keys[0],
        )
    except Exception as exc:  # noqa: BLE001 - report verification failure, exit 1
        logger.error("Seed verification failed: %s", exc)
        return 1

    logger.info("Seeding completed successfully")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
