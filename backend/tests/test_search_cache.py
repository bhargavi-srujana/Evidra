"""Unit + route tests for the search_cache repeat-query fast path."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

import app.core.config as cfg
from app.api.v1 import routes_search as rs
from app.main import app


@pytest.fixture(autouse=True)
def _settings():
    settings = cfg.get_settings()
    settings.OPENAI_API_KEY = "sk-test"
    settings.LLM_MIN_INTERVAL_SECONDS = 0
    # Force fail-fast on retryable errors here: these tests exercise the
    # route/cache layers, not the retry backoff (covered in test_llm_resilience).
    settings.LLM_MAX_RETRY_DELAY_SECONDS = 0.01
    yield


def _study_doc(sid="study-aaa", **design_over):
    design = {
        "population": "students",
        "sample_size": "n=50",
        "intervention": "sleep",
        "control": "wake",
        "task_type": "exams",
        "measurement_metric": "GPA",
        "study_duration": "1 semester",
        "study_type": "lab experiment",
    }
    design.update(design_over)
    return {
        "study_id": sid,
        "title": f"Title {sid}",
        "authors": [{"name": "A U Thor"}],
        "year": 2023,
        "venue": None,
        "doi": None,
        "abstract": "abstract",
        "url": None,
        "design": design,
    }


def _claim_doc(cid="c1", sid="study-aaa"):
    return {
        "claim_id": cid,
        "study_id": sid,
        "text": "Sleep improves grades",
        "effect_direction": "increases",
        "confidence_score": 0.9,
        "evidence_span": "sleep improves grades",
    }


def test_cache_key_stable_and_sensitive():
    assert rs._search_cache_key("Sleeping Grades") == rs._search_cache_key("  sleeping   grades ")
    assert rs._search_cache_key("sleep grades") != rs._search_cache_key("diet grades")


def test_coerce_slices_and_filters_claims():
    doc = {
        "results": [_study_doc("s1"), _study_doc("s2")],
        "claims": [_claim_doc("c1", "s1"), _claim_doc("c2", "s2")],
    }
    resp = rs._coerce_cached_response(doc, "raw query", max_results=1)
    assert resp is not None
    assert [s.study_id for s in resp.results] == ["s1"]
    assert [c.claim_id for c in resp.claims] == ["c1"]
    assert resp.query == "raw query"


def test_coerce_rejects_empty_or_corrupt():
    assert rs._coerce_cached_response({"results": [], "claims": []}, "q", 10) is None
    assert rs._coerce_cached_response({"results": [{"nope": 1}]}, "q", 10) is None


def test_is_cacheable_signal_rules():
    from app.models.claim import Claim
    from app.models.study import Study, StudyDesign

    empty_design = {f: "Not reported" for f in StudyDesign.model_fields}
    no_signal = [Study(**_study_doc())]
    no_signal[0].design = StudyDesign(**empty_design)
    assert rs._is_cacheable(no_signal, []) is False

    real = [Study(**_study_doc())]
    assert rs._is_cacheable(real, []) is True
    assert rs._is_cacheable(no_signal, [Claim(**_claim_doc())]) is True

    heuristic_only = [Claim(**{**_claim_doc(), "confidence_score": 0.3})]
    assert rs._is_cacheable(no_signal, heuristic_only) is False


class _FakeCollection:
    def __init__(self, doc=None):
        self.doc = doc
        self.deleted = []

    async def find_one(self, _filter):
        return self.doc

    async def delete_one(self, _filter):
        self.deleted.append(_filter)


class _FakeDB:
    def __init__(self, collection):
        self.collection = collection

    def __getitem__(self, _name):
        return self.collection


async def test_lookup_returns_fresh_doc():
    coll = _FakeCollection({"key": "k", "created_at": datetime.now(UTC)})
    with patch.object(rs, "get_db", return_value=_FakeDB(coll)):
        assert await rs._cache_lookup("k") is not None
        assert coll.deleted == []


async def test_lookup_evicts_stale_doc():
    stale = datetime.now(UTC) - timedelta(seconds=rs.SEARCH_CACHE_TTL_SECONDS + 10)
    coll = _FakeCollection({"key": "k", "created_at": stale})
    with patch.object(rs, "get_db", return_value=_FakeDB(coll)):
        assert await rs._cache_lookup("k") is None
        assert coll.deleted == [{"key": "k"}]


async def test_route_cache_hit_skips_pipeline():
    doc = {
        "results": [_study_doc("s1")],
        "claims": [_claim_doc("c1", "s1")],
        "created_at": datetime.now(UTC),
    }
    retrieve = AsyncMock(side_effect=AssertionError("retrieval must not run"))
    with (
        patch.object(rs, "_cache_lookup", AsyncMock(return_value=doc)),
        patch.object(rs, "_retrieve_papers", retrieve),
    ):
        resp = TestClient(app).post(
            "/api/v1/search", json={"query": "sleep grades", "max_results": 5}
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert [s["study_id"] for s in body["results"]] == ["s1"]
    assert body["claims"][0]["effect_direction"] == "increases"
    retrieve.assert_not_awaited()


async def test_route_miss_stores_cacheable_response():
    from app.services.common import RawPaper

    papers = [RawPaper(title="Paper One", snippet="Abstract one " * 20, year=2023)]
    payload = {
        "design": _study_doc("x")["design"],
        "claims": [_claim_doc("x-c1", "x")],
    }
    store = AsyncMock()
    with (
        patch.object(rs, "_cache_lookup", AsyncMock(return_value=None)),
        patch.object(rs, "_retrieve_papers", AsyncMock(return_value=papers)),
        patch(
            "app.services.extraction._chat_json",
            AsyncMock(return_value=payload),
        ),
        patch.object(rs, "_persist_studies_and_claims", AsyncMock()),
        patch.object(rs, "_cache_store", store),
    ):
        resp = TestClient(app).post(
            "/api/v1/search", json={"query": "sleep grades", "max_results": 5}
        )
    assert resp.status_code == 200, resp.text
    assert store.await_count == 1
    key, neutral, response = store.await_args.args
    assert key == rs._search_cache_key("sleep grades") == rs._search_cache_key(neutral)
    assert len(response.results) == 1


async def test_route_miss_with_total_failure_does_not_store():
    from app.services.common import RawPaper

    papers = [RawPaper(title="Paper One", snippet="Abstract one " * 20, year=2023)]
    store = AsyncMock()
    with (
        patch.object(rs, "_cache_lookup", AsyncMock(return_value=None)),
        patch.object(rs, "_retrieve_papers", AsyncMock(return_value=papers)),
        patch(
            "app.services.extraction._chat_json",
            AsyncMock(side_effect=Exception("429 quota")),
        ),
        patch.object(rs, "_persist_studies_and_claims", AsyncMock()),
        patch.object(rs, "_cache_store", store),
    ):
        resp = TestClient(app).post(
            "/api/v1/search", json={"query": "sleep grades", "max_results": 5}
        )
    assert resp.status_code == 200, resp.text
    store.assert_not_awaited()
