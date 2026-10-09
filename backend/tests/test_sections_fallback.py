"""Section selection, word cap, and zero-LLM heuristic fallback (no quota)."""

from unittest.mock import AsyncMock, patch

import pytest

import app.core.config as cfg
from app.services import extraction


@pytest.fixture(autouse=True)
def _settings():
    settings = cfg.get_settings()
    settings.OPENAI_API_KEY = "sk-test"
    settings.LLM_MIN_INTERVAL_SECONDS = 0
    settings.LLM_MAX_RETRY_DELAY_SECONDS = 0.01
    yield


def test_truncate_words_caps_long_input():
    text = "word " * 3000
    out = extraction._truncate_words(text)
    assert len(out.split()) == extraction.MAX_PAPER_WORDS == 2500


def test_truncate_words_leaves_short_input_untouched():
    assert extraction._truncate_words("short text") == "short text"


def test_build_paper_text_caps_words():
    out = extraction._build_paper_text("Title", "abstract " * 3000)
    assert len(out.split()) <= extraction.MAX_PAPER_WORDS


def test_select_sections_keeps_wanted_drops_rest():
    full = (
        "Introduction\nSome background.\n\n"
        "Abstract\nWe studied sleep.\n\n"
        "Methods\nWe did things.\n\n"
        "Results\nSleep improved grades N=120.\n\n"
        "References\n[1] Someone.\n\n"
        "Conclusion\nSleep matters.\n"
    )
    out = extraction._select_sections(full)
    assert "We studied sleep" in out
    assert "Sleep improved grades" in out
    assert "Sleep matters" in out
    assert "background" not in out
    assert "Someone" not in out


def test_select_sections_passes_through_bare_abstract():
    bare = "A plain provider abstract without headings."
    assert extraction._select_sections(bare) == bare


def test_heuristic_direction_matrix():
    assert extraction._heuristic_direction("Sleep improves memory") == "increases"
    assert extraction._heuristic_direction("Sleep loss impairs recall") == "decreases"
    assert extraction._heuristic_direction("No significant difference was found") == "no_effect"
    assert extraction._heuristic_direction("Benefits occur only when rested") == "conditional"
    assert extraction._heuristic_direction("A study of sleep patterns") == "unclear"


def test_heuristic_sample_size():
    assert extraction._heuristic_sample_size("With N=120 undergraduates") == "N=120"
    assert (
        extraction._heuristic_sample_size("24 participants completed the task") == "24 participants"
    )
    assert extraction._heuristic_sample_size("no numbers here") is None


def test_heuristic_population():
    assert extraction._heuristic_population("120 undergraduates slept less") == "College students"
    assert extraction._heuristic_population("mice were deprived") == "Mice"
    assert extraction._heuristic_population("nothing indicative") is None


async def test_fallback_end_to_end_zero_llm():
    design, claims = extraction.extract_study_fallback(
        "Sleep loss impairs recall in undergraduates (N=60, within-subject)",
        "Within-subject crossover; 60 undergraduates; sleep loss impairs recall.",
        "s1",
        intervention="sleeping less",
        outcome="grades",
    )
    assert design.population == "College students"
    assert design.sample_size == "N=60"
    assert design.intervention == "sleeping less"
    assert design.control == "Self-controlled / Baseline"
    assert design.measurement_metric == "grades"
    assert len(claims) == 1
    assert claims[0].effect_direction.value == "decreases"
    assert claims[0].confidence_score == pytest.approx(0.3)
    assert claims[0].study_id == "s1"


async def test_unified_rate_limit_wires_fallback_with_context():
    with patch.object(
        extraction,
        "_chat_json",
        AsyncMock(side_effect=Exception("Error 429 quota exceeded")),
    ):
        design, claims = await extraction.extract_study_unified(
            "Sleep improves grades",
            "N=40 students; sleep improves grades.",
            "s9",
            intervention="sleeping less",
            outcome="grades",
        )
    assert design.sample_size == "N=40"
    assert design.intervention == "sleeping less"
    assert len(claims) == 1
    # "improves" beats no negative cues, even anchored text is heuristic-only.
    assert claims[0].effect_direction.value == "increases"
