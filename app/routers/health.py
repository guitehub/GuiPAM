"""Endpoint /healthz pour le HEALTHCHECK Docker."""

from fastapi import APIRouter, Request, Response
from sqlalchemy import text

from app.database import get_engine

router = APIRouter()


@router.get("/healthz")
async def healthz(request: Request):
    try:
        engine = get_engine()
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception:
        return Response(content='{"status":"db_unreachable"}', media_type="application/json", status_code=503)
    scheduler = getattr(request.app.state, "scheduler", None)
    if scheduler is None or not scheduler.running:
        return Response(content='{"status":"scheduler_down"}', media_type="application/json", status_code=503)
    return {"status": "ok"}
