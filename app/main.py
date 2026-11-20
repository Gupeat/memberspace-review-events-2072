"""FastAPI application for the AI review-event service."""
from __future__ import annotations

import os

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.eval.api import error_response, router
from app.eval.errors import ReviewEventError


def create_app(session_factory: sessionmaker | None = None) -> FastAPI:
    if session_factory is None:
        url = os.environ.get("REVIEW_EVENT_DB_URL", "sqlite:///./review_events.db")
        engine = create_engine(url, future=True)
        session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    app = FastAPI(title="MemberSpace AI review events", version="1.0.0")
    app.state.session_factory = session_factory
    app.include_router(router)

    @app.exception_handler(ReviewEventError)
    async def handle_review_event_error(_: Request, exc: ReviewEventError) -> JSONResponse:
        return error_response(exc)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app


engine = create_engine(
    os.environ.get("REVIEW_EVENT_DB_URL", "sqlite:///./review_events.db"), future=True
)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
app = create_app(SessionLocal)
