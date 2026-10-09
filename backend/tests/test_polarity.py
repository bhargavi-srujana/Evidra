"""Polarity anchoring tests with a mocked LLM (no quota burned).

Covers the key scenario: the query asks about SLEEPING LESS, a paper shows
MORE sleep improves grades — the anchored pipeline must surface that claim
as "decreases" (sleeping less lowers grades), never "increases" just because
the abstract says "improves".

Note: the directional *judgment* itself is made by the LLM following the
v1.1.0 prompt anchor; what these tests pin down is that (a) the anchor is
injected into every unified prompt, and (b) the code path preserves a
correctly-anchored "decreases" verdict end to end instead of flipping it.
"""

from unittest.mock import AsyncMock, patch

import pytest

import app.core.config as cfg
from app.services import extraction


@pytest.fixture(autouse=True)
def _llm_settings():
    settings = cfg.get_settings()
    settings.OPENAI_API_KEY = "sk-test"
    settings.LLM_MIN_INTERVAL_SECONDS = 0
    yield


def _claim(direction="decreases"):
    return {
        "claim_id": "s-c1",
        "study_id": "s",
        "text": "More sleep improves grades",
        "effect_direction": direction,
        "confidence_score": 0.85,
        "evidence_span": "more sleep improves grades",
    }


def _payload(direction="decreases"):
    return {
        "design": {
            "population": "students",
            "sample_size": "n=100",
            "intervention": "sleep duration",
            "control": "restricted sleep",
            "task_type": "exams",
            "measurement_metric": "GPA",
            "study_duration": "1 semester",
            "study_type": "observational",
        },
        "claims": [_claim(direction)],
    }


async def test_anchor_question_injected_into_prompt():
    captured = {}

    async def fake_chat_json(system, user):
        captured["user"] = user
        return _payload()

    with patch.object(extraction, "_chat_json", side_effect=fake_chat_json):
        await extraction.extract_study_unified(
            "T", "abstract", "s", intervention="sleeping less", outcome="grades"
        )
    assert "Does sleeping less increase grades?" in captured["user"]
    assert "do NOT mean" in captured["user"]  # polarity rule block present


async def test_positive_words_not_flipped_to_increases():
    """A 'more sleep improves grades' finding stays "decreases" relative to
    the sleeping-less intervention through the whole pipeline."""
    with patch.object(extraction, "_chat_json", AsyncMock(return_value=_payload("decreases"))):
        design, claims = await extraction.extract_study_unified(
            "T", "abstract", "s", intervention="sleeping less", outcome="grades"
        )
    assert design.population == "students"
    assert len(claims) == 1
    assert claims[0].text == "More sleep improves grades"
    assert claims[0].effect_direction.value == "decreases"
    assert claims[0].study_id == "s"


async def test_unified_makes_exactly_one_llm_call():
    with patch.object(extraction, "_chat_json", AsyncMock(return_value=_payload())) as chat:
        await extraction.extract_study_unified("T", "abstract", "s")
    assert chat.await_count == 1


async def test_unified_rate_limit_uses_heuristic_fallback():
    with patch.object(extraction, "_chat_json", AsyncMock(side_effect=Exception("429 quota"))):
        design, claims = await extraction.extract_study_unified("T", "abstract", "s")
    assert design.population == "Not reported"
    assert len(claims) == 1
    assert claims[0].effect_direction.value == "unclear"
    assert claims[0].confidence_score == pytest.approx(0.3)


async def test_unified_non_rate_limit_failure_falls_back_empty():
    with patch.object(extraction, "_chat_json", AsyncMock(side_effect=Exception("boom"))):
        design, claims = await extraction.extract_study_unified("T", "abstract", "s")
    assert design.population == "Not reported"
    assert claims == []


def test_unified_prompt_is_v11_with_placeholders():
    prompt = extraction.load_prompt(extraction.UNIFIED_PROMPT_FILE)
    assert prompt["version"] == "1.2.0"
    assert prompt["output_contract"]["type"] == "object"
    assert "{intervention}" in prompt["user_template"]
    assert "{outcome}" in prompt["user_template"]
