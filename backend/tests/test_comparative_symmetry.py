"""Opposite-phrasing symmetry for group-comparison questions.

"do men sleep more than women" vs "do women sleep more when compared to men"
must retrieve the SAME corpus (symmetric neutral query) while anchoring
opposite verdicts (mirrored interventions/anchors). Otherwise live providers
return different papers per phrasing and the overview counts diverge for no
scientific reason.
"""

from unittest.mock import AsyncMock, patch

import app.core.config as cfg
from app.services import extraction
from app.services.query_parser import parse_query


def test_opposite_phrasings_share_neutral_query():
    a = parse_query("do men sleep more than women")
    b = parse_query("do women sleep more when compared to men")
    assert a.neutral_search_query
    assert a.neutral_search_query == b.neutral_search_query


def test_opposite_phrasings_mirror_anchor():
    a = parse_query("do men sleep more than women")
    b = parse_query("do women sleep more when compared to men")
    assert a.intervention == "men (compared to women)"
    assert b.intervention == "women (compared to men)"
    assert a.outcome == b.outcome == "sleep"
    assert a.anchor_question == "Do men sleep more than women?"
    assert b.anchor_question == "Do women sleep more than men?"


def test_less_variant_shares_corpus_with_more_variant():
    # Polarity lives in the anchor, not the retrieval query.
    a = parse_query("do men sleep more than women")
    b = parse_query("do men sleep less than women")
    assert a.neutral_search_query == b.neutral_search_query
    assert a.expected_direction == "positive"
    assert b.expected_direction == "negative"


async def test_natural_anchor_replaces_templated_form():
    captured = {}

    async def fake_chat_json(system, user):
        captured["user"] = user
        return {"design": {}, "claims": []}

    settings = cfg.get_settings()
    settings.OPENAI_API_KEY = "sk-test"
    settings.LLM_MIN_INTERVAL_SECONDS = 0
    with patch.object(extraction, "_chat_json", side_effect=fake_chat_json):
        await extraction.extract_study_unified(
            "T",
            "abstract",
            "s",
            intervention="men (compared to women)",
            outcome="sleep",
            anchor_question="Do men sleep more than women?",
        )
    assert "Do men sleep more than women?" in captured["user"]
    assert "Does men (compared to women) increase sleep?" not in captured["user"]


async def test_default_anchor_unchanged_without_anchor_question():
    captured = {}

    async def fake_chat_json(system, user):
        captured["user"] = user
        return {"design": {}, "claims": []}

    settings = cfg.get_settings()
    settings.OPENAI_API_KEY = "sk-test"
    settings.LLM_MIN_INTERVAL_SECONDS = 0
    with patch.object(extraction, "_chat_json", side_effect=fake_chat_json):
        await extraction.extract_study_unified(
            "T", "abstract", "s", intervention="sleeping less", outcome="grades"
        )
    assert "Does sleeping less increase grades?" in captured["user"]


def test_degradation_warnings_none_when_all_llm():
    from app.api.v1 import routes_search as rs
    from app.models.study import Study

    studies = [
        Study(
            study_id="s1",
            title="T",
            authors=[],
            year=2020,
            abstract="a",
            design={n: "x" for n in Study.model_fields["design"].annotation.model_fields},
        )
    ]
    assert rs._degradation_warnings(studies) == []


def test_degradation_warnings_all_fallback():
    from app.api.v1 import routes_search as rs
    from app.models.study import Study

    design_fields = Study.model_fields["design"].annotation.model_fields
    studies = [
        Study(
            study_id=f"s{i}",
            title="T",
            authors=[],
            year=2020,
            abstract="a",
            design={n: "x" for n in design_fields},
            is_fallback=True,
        )
        for i in range(3)
    ]
    warnings = rs._degradation_warnings(studies)
    assert len(warnings) == 1
    assert "could not analyze" in warnings[0]


def test_degradation_warnings_partial_counts():
    from app.api.v1 import routes_search as rs
    from app.models.study import Study

    design_fields = Study.model_fields["design"].annotation.model_fields
    kwargs = dict(title="T", authors=[], year=2020, abstract="a")

    def make(sid, fallback):
        return Study(
            study_id=sid,
            design={n: "x" for n in design_fields},
            is_fallback=fallback,
            **kwargs,
        )

    warnings = rs._degradation_warnings([make("s1", True), make("s2", False)])
    assert len(warnings) == 1
    assert "1 of 2" in warnings[0]


async def test_quota_exhausted_run_returns_warnings_not_silence():
    """All-429 run: HTTP 200 with heuristic verdicts AND a warning, so "all
    Unclear" is never mistaken for consensus."""
    from unittest.mock import AsyncMock

    from fastapi.testclient import TestClient

    from app.api.v1 import routes_search as rs
    from app.main import app
    from app.services.common import RawPaper

    settings = cfg.get_settings()
    settings.OPENAI_API_KEY = "sk-test"
    settings.LLM_MIN_INTERVAL_SECONDS = 0
    settings.LLM_MAX_RETRY_DELAY_SECONDS = 0.01

    papers = [RawPaper(title="Paper One", snippet="Abstract one " * 20, year=2023)]
    with (
        patch.object(rs, "_cache_lookup", AsyncMock(return_value=None)),
        patch.object(rs, "_retrieve_papers", AsyncMock(return_value=papers)),
        patch(
            "app.services.extraction._chat_json",
            AsyncMock(side_effect=Exception("429 quota exhausted")),
        ),
        patch.object(rs, "_persist_studies_and_claims", AsyncMock()),
        patch.object(rs, "_cache_store", AsyncMock()),
    ):
        resp = TestClient(app).post(
            "/api/v1/search", json={"query": "do men sleep more than women", "max_results": 1}
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["results"][0]["is_fallback"] is True
    assert body["warnings"] and "could not analyze" in body["warnings"][0]
    assert body["anchor_question"] == "Do men sleep more than women?"
