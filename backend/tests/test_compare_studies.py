"""Compare works off caller-supplied studies when Mongo is unavailable."""

from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app


def _study(sid, title=None):
    title = title or f"Title {sid}"
    return {
        "study_id": sid,
        "title": title,
        "authors": [{"name": "A U Thor"}],
        "year": 2023,
        "venue": None,
        "doi": None,
        "abstract": "abstract",
        "url": None,
        "design": {
            "population": "students",
            "sample_size": "n=50",
            "intervention": "sleep",
            "control": "wake",
            "task_type": "exams",
            "measurement_metric": "GPA",
            "study_duration": "1 semester",
            "study_type": "lab experiment",
        },
    }


def _claim(cid, sid, direction="increases"):
    return {
        "claim_id": cid,
        "study_id": sid,
        "text": "Sleep improves grades",
        "effect_direction": direction,
        "confidence_score": 0.9,
        "evidence_span": "sleep improves grades",
    }


def _post(body):
    return TestClient(app).post("/api/v1/compare", json=body)


def test_supplied_studies_survive_store_outage():
    """Search succeeded (best-effort persist failed / Mongo down) but the
    client still has studies+claims: comparison must succeed, not 503."""
    body = {
        "study_ids": ["s1", "s2"],
        "claims": [_claim("c1", "s1"), _claim("c2", "s2")],
        "studies": [_study("s1", "Fresh Title One"), _study("s2")],
    }
    with patch(
        "app.api.v1.routes_compare.get_db", side_effect=Exception("mongo down")
    ):
        resp = _post(body)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["summary"]["total_studies"] == 2
    assert data["summary"]["positive_count"] == 2


def test_supplied_studies_beat_stale_store():
    """When both sources cover an ID, the caller-supplied (fresher) record
    is used without touching missing store docs."""
    from app.api.v1 import routes_compare as rc

    async def _boom(*args, **kwargs):
        raise AssertionError("store must not be consulted")

    body = {
        "study_ids": ["s1", "s2"],
        "claims": [_claim("c1", "s1"), _claim("c2", "s2")],
        "studies": [_study("s1"), _study("s2")],
    }
    with patch.object(rc, "get_db", side_effect=_boom):
        resp = _post(body)
    assert resp.status_code == 200, resp.text


def test_store_outage_without_supply_still_503s():
    """Nothing supplied and nothing reachable: honest 503, not fabrication."""
    body = {"study_ids": ["s1", "s2"], "claims": [_claim("c1", "s1")]}
    with patch(
        "app.api.v1.routes_compare.get_db", side_effect=Exception("mongo down")
    ):
        resp = _post(body)
    assert resp.status_code == 503, resp.text


def test_partial_supply_with_outage_still_503s():
    """One uncovered ID and a dead store: cannot compare, 503."""
    body = {
        "study_ids": ["s1", "s2"],
        "claims": [_claim("c1", "s1")],
        "studies": [_study("s1")],
    }
    with patch(
        "app.api.v1.routes_compare.get_db", side_effect=Exception("mongo down")
    ):
        resp = _post(body)
    assert resp.status_code == 503, resp.text
