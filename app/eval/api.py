"""HTTP API for review-event ingestion."""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.eval.errors import ReviewEventError, invalid
from app.eval.service import submit_review_events

router = APIRouter(prefix="/api/eval", tags=["eval"])


def get_session(request: Request) -> Session:
    factory = request.app.state.session_factory
    session = factory()
    try:
        yield session
    finally:
        session.close()


def _org_id(request: Request) -> uuid.UUID:
    raw = request.headers.get("X-Org-Id")
    if not raw:
        return uuid.UUID(int=0)
    try:
        return uuid.UUID(raw)
    except ValueError:
        raise invalid("ORG_INVALID", "X-Org-Id must be a UUID") from None


def _actor_id(request: Request) -> uuid.UUID | None:
    raw = request.headers.get("X-Actor-Id")
    if not raw:
        return None
    try:
        return uuid.UUID(raw)
    except ValueError:
        raise invalid("ACTOR_INVALID", "X-Actor-Id must be a UUID") from None


@router.post("/review-events")
async def ingest_review_events(
    request: Request, session: Session = Depends(get_session)
) -> JSONResponse:
    try:
        payload = await request.json()
    except Exception:
        raise invalid("REQUEST_INVALID", "request body must be valid JSON") from None

    if isinstance(payload, dict):
        events: Any = payload.get("events")
    elif isinstance(payload, list):
        events = payload
    else:
        events = None

    result = submit_review_events(session, _org_id(request), events, _actor_id(request))
    body = result.as_dict()
    return JSONResponse(status_code=200, content=body)


def error_response(error: ReviewEventError) -> JSONResponse:
    return JSONResponse(status_code=error.status_code, content=error.as_dict())
