"""Versioned API router aggregation."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.routes_compare import router as compare_router
from app.api.v1.routes_search import router as search_router
from app.api.v1.routes_studies import router as studies_router

api_router = APIRouter()
api_router.include_router(search_router)
api_router.include_router(studies_router)
api_router.include_router(compare_router)
