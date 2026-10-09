"""Unit tests for deterministic query normalization (no LLM involved)."""

from unittest.mock import AsyncMock, patch

import pytest

import app.core.config as cfg
from app.services import query_parser
from app.services.query_parser import aparse_query, parse_query


@pytest.fixture(autouse=True)
def _clean_parser_cache():
    query_parser.clear_llm_query_cache()
    yield
    query_parser.clear_llm_query_cache()


def test_outcome_first_passive_sleep_less():
    parsed = parse_query("does grades improve by sleeping less?")
    assert parsed.intervention == "sleeping less"
    assert parsed.outcome == "grades"
    assert parsed.expected_direction == "positive"
    assert "less" not in parsed.neutral_search_query.split()
    assert "?" not in parsed.neutral_search_query
    assert "sleeping" in parsed.neutral_search_query
    assert "grades" in parsed.neutral_search_query


def test_active_positive_verb():
    parsed = parse_query("does sleeping less improve grades")
    assert parsed.intervention == "sleeping less"
    assert parsed.outcome == "grades"
    assert parsed.expected_direction == "positive"


def test_active_negative_verb():
    parsed = parse_query("does sleep deprivation decrease academic performance")
    assert parsed.intervention == "sleep deprivation"
    assert parsed.outcome == "academic performance"
    assert parsed.expected_direction == "negative"


def test_effect_of_pattern():
    parsed = parse_query("What is the effect of sleep deprivation on academic performance?")
    assert parsed.intervention == "sleep deprivation"
    assert parsed.outcome == "academic performance"
    assert parsed.expected_direction == "unclear"


def test_link_between_pattern():
    parsed = parse_query("Is there a link between sleep duration and GPA?")
    assert parsed.intervention == "sleep duration"
    assert parsed.outcome == "gpa"
    assert parsed.expected_direction == "unclear"


def test_keyword_fallback_has_no_entities():
    parsed = parse_query("sleep memory consolidation")
    assert parsed.intervention == ""
    assert parsed.outcome == ""
    assert parsed.expected_direction == "unclear"
    assert parsed.neutral_search_query != ""


def test_empty_query_never_raises():
    parsed = parse_query("")
    assert parsed.neutral_search_query == ""
    assert parsed.expected_direction == "unclear"


def test_comparative_than_anchors_group_a_vs_b():
    parsed = parse_query("do men sleep more than women")
    assert parsed.intervention == "men (compared to women)"
    assert parsed.outcome == "sleep"
    assert parsed.expected_direction == "positive"
    assert "more" not in parsed.neutral_search_query.split()


def test_comparative_when_compared_to():
    parsed = parse_query("do men sleep more when compared to women")
    assert parsed.intervention == "men (compared to women)"
    assert parsed.outcome == "sleep"
    assert parsed.expected_direction == "positive"


def test_opposite_comparatives_anchor_oppositely():
    q1 = parse_query("do men sleep more when compared to women")
    q2 = parse_query("do women sleep more when compared to men")
    assert q1.intervention != q2.intervention
    assert q1.outcome == q2.outcome == "sleep"
    # Same literature either way: neutral terms agree as sets.
    assert sorted(q1.neutral_search_query.split()) == sorted(
        q2.neutral_search_query.split()
    )


def test_comparative_less_is_negative():
    parsed = parse_query("do men sleep less than women")
    assert parsed.intervention == "men (compared to women)"
    assert parsed.expected_direction == "negative"


def test_verb_pattern_beats_comparative_shape():
    # "does X improve Y more than Z" keeps its verb-anchored parse.
    parsed = parse_query("does coffee improve focus more than tea")
    assert parsed.intervention == "coffee"
    assert parsed.expected_direction == "positive"


def _llm_settings(**over):
    settings = cfg.get_settings()
    settings.OPENAI_API_KEY = "sk-test"
    settings.LLM_MIN_INTERVAL_SECONDS = 0
    for key, value in over.items():
        setattr(settings, key, value)
    return settings


async def test_aparse_rule_hit_costs_no_llm():
    _llm_settings()
    with patch(
        "app.services.extraction._chat_json", AsyncMock()
    ) as chat:
        parsed = await aparse_query("does sleeping less improve grades")
    assert parsed.intervention == "sleeping less"
    chat.assert_not_awaited()


async def test_aparse_llm_fallback_anchors_missed_shape():
    _llm_settings()
    llm_payload = {
        "intervention": "coffee",
        "outcome": "sleep quality",
        "expected_direction": "negative",
        "neutral_search_query": "coffee sleep quality",
    }
    with patch(
        "app.services.extraction._chat_json", AsyncMock(return_value=llm_payload)
    ):
        parsed = await aparse_query("is coffee bad for sleep")
    assert parsed.intervention == "coffee"
    assert parsed.outcome == "sleep quality"
    assert parsed.expected_direction == "negative"
    assert "coffee" in parsed.neutral_search_query


async def test_aparse_llm_caches_by_question():
    _llm_settings()
    llm_payload = {
        "intervention": "coffee",
        "outcome": "sleep quality",
        "expected_direction": "negative",
        "neutral_search_query": "coffee sleep quality",
    }
    with patch(
        "app.services.extraction._chat_json", AsyncMock(return_value=llm_payload)
    ) as chat:
        first = await aparse_query("is coffee bad for sleep")
        second = await aparse_query("is coffee bad for sleep")
    assert first.intervention == second.intervention == "coffee"
    assert chat.await_count == 1


async def test_aparse_invalid_direction_coerces_unclear():
    _llm_settings()
    llm_payload = {
        "intervention": "x",
        "outcome": "y",
        "expected_direction": "sideways",
        "neutral_search_query": "x y",
    }
    with patch(
        "app.services.extraction._chat_json", AsyncMock(return_value=llm_payload)
    ):
        parsed = await aparse_query("is coffee bad for sleep")
    assert parsed.expected_direction == "unclear"


async def test_aparse_llm_failure_returns_rule_fallback():
    _llm_settings()
    with patch(
        "app.services.extraction._chat_json", AsyncMock(side_effect=Exception("boom"))
    ):
        parsed = await aparse_query("is coffee bad for sleep")
    assert parsed.intervention == ""
    assert parsed.outcome == ""
    assert parsed.neutral_search_query != ""


async def test_aparse_flag_off_skips_llm():
    _llm_settings(LLM_QUERY_PARSER=False)
    with patch(
        "app.services.extraction._chat_json", AsyncMock()
    ) as chat:
        parsed = await aparse_query("is coffee bad for sleep")
    assert parsed.intervention == ""
    chat.assert_not_awaited()
