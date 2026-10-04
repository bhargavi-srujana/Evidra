"""Corpus-level research-gap detection (deterministic, no LLM).

Every gap is strictly framed around the retrieved corpus ("In the retrieved
corpus, ...") — never a global claim about what exists in the literature.
Pure string analysis, so it is fast and cannot hallucinate.
"""

from __future__ import annotations

import re

from app.models.study import Study

MAX_GAPS = 6
MIN_REPORT_RATE = 0.5  # dimension reported in fewer than half the studies -> gap
SMALL_SAMPLE_MAX = 50
_INT_RE = re.compile(r"\d[\d,]*")

_DIMENSION_LABELS: tuple[tuple[str, str], ...] = (
    ("population", "population"),
    ("sample_size", "sample size"),
    ("intervention", "intervention"),
    ("control", "control group"),
    ("task_type", "task type"),
    ("measurement_metric", "measurement metric"),
    ("study_duration", "study duration"),
    ("study_type", "study type / setting"),
)

# Population segments worth checking for coverage in the corpus.
_POPULATION_SEGMENTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("senior developers or experts", ("senior", "expert", "experienced")),
    ("junior developers or novices", ("junior", "novice", "beginner")),
    ("students", ("student", "undergrad", "pupil")),
    (
        "professional practitioners",
        ("professional", "practitioner", "engineer", "developer", "programmer"),
    ),
)

_SETTING_SIGNALS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("controlled lab experiments", ("lab", "controlled", "experiment")),
    ("field or industrial studies", ("field", "industr", "case study", "in situ")),
)

_LONGITUDINAL_SIGNALS = ("longitudinal", "months", "month", "weeks", "year")


# Placeholders that mean "not stated" (see DESIGN_FALLBACK in
# app/services/extraction.py): excluded so fallback text never counts as
# reported coverage and never triggers false zero-variation gaps.
_PLACEHOLDER_VALUES = frozenset(
    {
        "",
        "null",
        "none",
        "n/a",
        "na",
        "unknown",
        "unspecified",
        "not reported",
        "not stated",
        "not specified",
        "not available",
        "not provided",
        "not mentioned",
        "unclear",
        "not applicable",
    }
)


def _design_values(studies: list[Study], field: str) -> list[str]:
    values: list[str] = []
    for study in studies:
        raw = getattr(study.design, field, None)
        if not isinstance(raw, str):
            continue
        text = raw.strip()
        if text and text.lower().rstrip(".") not in _PLACEHOLDER_VALUES:
            values.append(text)
    return values


def _mentions(values: list[str], signals: tuple[str, ...]) -> bool:
    blob = " ".join(values).lower()
    return any(s in blob for s in signals)


def _parse_int(value: str) -> int | None:
    match = _INT_RE.search(value.replace(",", ""))
    return int(match.group(0)) if match else None


def detect_research_gaps(studies: list[Study]) -> list[str]:
    """Spot missing/under-represented parameter spaces in the corpus."""
    total = len(studies)
    if total == 0:
        return ["In the retrieved corpus, no studies were available for analysis."]
    gaps: list[str] = []

    # 1. Under-reported PICO dimensions (limits comparability).
    for field, label in _DIMENSION_LABELS:
        reported = len(_design_values(studies, field))
        if reported / total < MIN_REPORT_RATE:
            gaps.append(
                f"In the retrieved corpus, {label} is reported in only "
                f"{reported} of {total} studies, limiting comparability on "
                f"that dimension."
            )

    # 2. Zero-variation dimensions (generalizability untested).
    for field, label in _DIMENSION_LABELS:
        values = _design_values(studies, field)
        if values and len({v.lower() for v in values}) == 1:
            gaps.append(
                f"In the retrieved corpus, all studies reporting {label} use "
                f"'{values[0]}', so variation in {label} is untested."
            )

    # 3. Population-segment coverage.
    populations = _design_values(studies, "population")
    if populations:
        for segment, signals in _POPULATION_SEGMENTS:
            if not _mentions(populations, signals):
                gaps.append(f"In the retrieved corpus, few studies evaluate " f"{segment}.")

    # 4. Sample-size scale.
    sizes = [n for v in _design_values(studies, "sample_size") if (n := _parse_int(v)) is not None]
    if sizes and max(sizes) < SMALL_SAMPLE_MAX:
        gaps.append(
            f"In the retrieved corpus, the largest reported sample is "
            f"{max(sizes)}, so large-scale evidence (n>={SMALL_SAMPLE_MAX}) "
            f"is missing."
        )

    # 5. Setting balance (lab vs field).
    study_types = _design_values(studies, "study_type")
    if study_types:
        for setting, signals in _SETTING_SIGNALS:
            if not _mentions(study_types, signals):
                gaps.append(f"In the retrieved corpus, few studies use " f"{setting}.")

    # 6. Temporal depth.
    durations = _design_values(studies, "study_duration")
    if durations and not _mentions(durations, _LONGITUDINAL_SIGNALS):
        gaps.append(
            "In the retrieved corpus, few studies track effects over time, "
            "so longitudinal evidence is thin."
        )

    if not gaps:
        gaps.append(
            "In the retrieved corpus, coverage across PICO dimensions is "
            "reasonably broad; no dominant gap stands out."
        )
    return gaps[:MAX_GAPS]


__all__ = ["detect_research_gaps"]
