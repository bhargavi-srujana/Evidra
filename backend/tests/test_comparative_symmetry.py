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
