"""Unit tests for deterministic query normalization (no LLM involved)."""

from app.services.query_parser import parse_query


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
