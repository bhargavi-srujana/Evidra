"""GET /api/v1/studies/{study_id} — stub returning a schema-valid mock study."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.models.study import Study

router = APIRouter(tags=["studies"])


@router.get("/studies/{study_id}", response_model=Study)
async def get_study(study_id: str) -> Study:
    if not study_id.strip():
        raise HTTPException(status_code=404, detail="Study not found")
    return Study(
        study_id=study_id,
        title=f"Mock study detail for {study_id}",
        authors=[{"name": "Ada Lovelace"}],
        year=2023,
        venue="Not reported",
        doi=None,
        abstract="Mock abstract for stub study detail. Real persistence lands in Phase 3.",
        url=None,
        design={"population": "Not reported"},
    )
