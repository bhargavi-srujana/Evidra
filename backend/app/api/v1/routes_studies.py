"""GET /api/v1/studies/{study_id} — fetch a persisted study by ID."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from app.db.mongo import get_db
from app.models.study import Study

logger = logging.getLogger(__name__)

router = APIRouter(tags=["studies"])


@router.get("/studies/{study_id}", response_model=Study)
async def get_study(study_id: str) -> Study:
    if not study_id or not study_id.strip():
        raise HTTPException(status_code=404, detail="Study not found")
    try:
        doc = await get_db()["studies"].find_one({"study_id": study_id})
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Study store unavailable: {exc}. Run POST /search first.",
        ) from exc
    if not doc:
        raise HTTPException(status_code=404, detail=f"Study not found: {study_id}")
    doc = {k: v for k, v in doc.items() if k not in ("_id", "updated_at")}
    try:
        return Study(**doc)
    except Exception as exc:
        logger.warning("Invalid study doc %r: %s", study_id, exc)
        raise HTTPException(status_code=404, detail=f"Study not found: {study_id}") from exc
