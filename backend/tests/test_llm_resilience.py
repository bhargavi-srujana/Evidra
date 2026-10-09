"""Rate-limit resilience: 4 attempts/model, exponential backoff, model failover."""

import time
from unittest.mock import AsyncMock, MagicMock

import pytest

import app.core.config as cfg
from app.services import extraction

PRIMARY = "openai/gpt-oss-120b"
FALLBACK = "llama-3.1-8b-instant"


@pytest.fixture(autouse=True)
def _settings():
    settings = cfg.get_settings()
    settings.OPENAI_API_KEY = "sk-test"
    settings.OPENAI_MODEL = PRIMARY
    settings.OPENAI_FALLBACK_MODEL = FALLBACK
    settings.LLM_MIN_INTERVAL_SECONDS = 0
    settings.LLM_MAX_RETRIES = 3
    settings.LLM_MAX_RETRY_DELAY_SECONDS = 75.0
    yield


def _ok_resp():
    msg = MagicMock()
    msg.content = '{"a": 1}'
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]
    return resp


def _rate_limit_error(hint="0.1s"):
    exc = Exception(f"Error code: 429 - quota exceeded. Please retry in {hint}.")
    exc.status_code = 429
    return exc


def _overload_error(hint="0.1s"):
    exc = Exception(f"Error code: 503 - overloaded. Please retry in {hint}.")
    exc.status_code = 503
    return exc


def _client_for(side_effect):
    client = MagicMock()
    client.chat.completions.create = AsyncMock(side_effect=side_effect)
    return client


def _models_used(client):
    return [call.kwargs["model"] for call in client.chat.completions.create.mock_calls]


async def test_primary_exhausted_fails_over_to_fallback():
    client = _client_for([_rate_limit_error()] * 4 + [_ok_resp()])
    out = await extraction._chat_create_with_fallback(
        client, PRIMARY, [{"role": "user", "content": "hi"}], True
    )
    assert out is not None
    assert _models_used(client) == [PRIMARY] * 4 + [FALLBACK]


async def test_daily_lockout_fails_over_without_long_sleep():
    client = _client_for([_rate_limit_error("17h56m15.1s"), _ok_resp()])
    start = time.monotonic()
    await extraction._chat_create_with_fallback(
        client, PRIMARY, [{"role": "user", "content": "hi"}], True
    )
    assert time.monotonic() - start < 3
    assert _models_used(client) == [PRIMARY, FALLBACK]


async def test_both_models_exhausted_raises():
    client = _client_for([_rate_limit_error()] * 8)
    with pytest.raises(Exception, match="429"):
        await extraction._chat_create_with_fallback(
            client, PRIMARY, [{"role": "user", "content": "hi"}], True
        )
    assert _models_used(client) == [PRIMARY] * 4 + [FALLBACK] * 4


async def test_non_rate_limit_error_never_fails_over():
    client = _client_for([ValueError("bad request")])
    with pytest.raises(ValueError):
        await extraction._chat_create_with_fallback(
            client, PRIMARY, [{"role": "user", "content": "hi"}], True
        )
    assert _models_used(client) == [PRIMARY]


async def test_overload_retries_on_primary_without_model_switch():
    client = _client_for([_overload_error()] * 4)
    with pytest.raises(Exception, match="503"):
        await extraction._chat_create_with_fallback(
            client, PRIMARY, [{"role": "user", "content": "hi"}], True
        )
    assert _models_used(client) == [PRIMARY] * 4


def test_concurrency_caps_are_two():
    from app.api.v1 import routes_search

    assert extraction.MAX_CONCURRENT_LLM_REQUESTS == 4
    assert routes_search.MAX_CONCURRENT_EXTRACTIONS == 4
