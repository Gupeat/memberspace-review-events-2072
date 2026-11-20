"""Shared SQLAlchemy infrastructure for the AI review event store."""
from __future__ import annotations

import os
import uuid
from datetime import datetime

from sqlalchemy import DateTime, MetaData, Uuid, create_engine, event, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

DEFAULT_URL = "sqlite:///./review_events.db"
ENV_VAR = "REVIEW_EVENT_DB_URL"

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class SystemFieldsMixin:
    """Unified system columns required by the platform."""

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    site_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


def database_url() -> str:
    return os.environ.get(ENV_VAR, DEFAULT_URL)


def create_db_engine(url: str | None = None):
    target = url or database_url()
    engine = create_engine(target, future=True)
    if target.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def _sqlite_foreign_keys(dbapi_connection, _connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()
    return engine
