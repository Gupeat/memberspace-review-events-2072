"""SQLAlchemy models for AI review events and the reject-reason dictionary."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, SystemFieldsMixin
from app.eval.constants import GLOBAL_ORG_ID

_EVENT_TYPES_SQL = "'ai_draft_created','review_opened','review_submitted','draft_expired'"
_ACTIONS_SQL = "'adopted_as_is','adopted_with_edits','rejected'"
_REASONS_SQL = (
    "'factual_error','off_tone','missing_info','policy_violation',"
    "'duplicate','not_needed','other'"
)


class AiReviewEvent(Base):
    """One append-only AI review event. id is the caller-supplied event_id."""

    __tablename__ = "ai_review_event"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    org_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    site_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    tool: Mapped[str | None] = mapped_column(String(64), nullable=True)
    scenario: Mapped[str | None] = mapped_column(String(64), nullable=True)
    draft_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    prompt_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    model_profile: Mapped[str | None] = mapped_column(String(64), nullable=True)
    output_chars: Mapped[int | None] = mapped_column(Integer, nullable=True)
    structured_field_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    action: Mapped[str | None] = mapped_column(String(32), nullable=True)
    final_ref: Mapped[str | None] = mapped_column(String(512), nullable=True)
    final_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reviewer_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    review_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reject_reason_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    reject_reason_note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
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

    __table_args__ = (
        CheckConstraint(f"event_type IN ({_EVENT_TYPES_SQL})", name="event_type"),
        CheckConstraint(f"action IS NULL OR action IN ({_ACTIONS_SQL})", name="action"),
        CheckConstraint(
            f"reject_reason_code IS NULL OR reject_reason_code IN ({_REASONS_SQL})",
            name="reject_reason_code",
        ),
        CheckConstraint(
            "event_type <> 'ai_draft_created' OR ("
            "tool IS NOT NULL AND scenario IS NOT NULL AND prompt_version IS NOT NULL "
            "AND output_chars IS NOT NULL AND structured_field_count IS NOT NULL)",
            name="draft_created_fields",
        ),
        CheckConstraint(
            "event_type <> 'review_opened' OR reviewer_id IS NOT NULL",
            name="review_opened_fields",
        ),
        CheckConstraint(
            "event_type <> 'review_submitted' OR ("
            "action IS NOT NULL AND reviewer_id IS NOT NULL AND final_ref IS NOT NULL "
            "AND final_hash IS NOT NULL AND review_seconds IS NOT NULL)",
            name="review_submitted_fields",
        ),
        CheckConstraint(
            "event_type <> 'review_submitted' OR ("
            "(action = 'rejected' AND reject_reason_code IS NOT NULL) OR "
            "(action <> 'rejected' AND reject_reason_code IS NULL))",
            name="rejected_requires_reason",
        ),
        CheckConstraint(
            "reject_reason_code IS NULL OR reject_reason_code <> 'other' OR ("
            "reject_reason_note IS NOT NULL AND length(trim(reject_reason_note)) > 0)",
            name="other_requires_note",
        ),
        CheckConstraint(
            "reject_reason_code = 'other' OR reject_reason_note IS NULL",
            name="note_only_for_other",
        ),
        CheckConstraint(
            "event_type <> 'ai_draft_created' OR ("
            "action IS NULL AND final_ref IS NULL AND final_hash IS NULL AND reviewer_id IS NULL "
            "AND review_seconds IS NULL AND reject_reason_code IS NULL AND reject_reason_note IS NULL)",
            name="draft_created_no_review_fields",
        ),
        CheckConstraint(
            "event_type <> 'review_opened' OR ("
            "action IS NULL AND final_ref IS NULL AND final_hash IS NULL AND review_seconds IS NULL "
            "AND reject_reason_code IS NULL AND reject_reason_note IS NULL)",
            name="review_opened_no_result_fields",
        ),
        CheckConstraint(
            "event_type <> 'review_submitted' OR ("
            "tool IS NULL AND scenario IS NULL AND prompt_version IS NULL AND model_profile IS NULL "
            "AND output_chars IS NULL AND structured_field_count IS NULL)",
            name="review_submitted_no_draft_fields",
        ),
        CheckConstraint(
            "event_type <> 'draft_expired' OR ("
            "tool IS NULL AND scenario IS NULL AND prompt_version IS NULL AND model_profile IS NULL "
            "AND output_chars IS NULL AND structured_field_count IS NULL AND action IS NULL "
            "AND final_ref IS NULL AND final_hash IS NULL AND reviewer_id IS NULL "
            "AND review_seconds IS NULL AND reject_reason_code IS NULL AND reject_reason_note IS NULL)",
            name="expired_no_extra_fields",
        ),
        CheckConstraint(
            "final_hash IS NULL OR length(final_hash) = 64", name="final_hash_length"
        ),
        CheckConstraint(
            "review_seconds IS NULL OR (review_seconds >= 0 AND review_seconds <= 86400)",
            name="review_seconds_range",
        ),
        CheckConstraint(
            "output_chars IS NULL OR output_chars >= 0", name="output_chars_non_negative"
        ),
        CheckConstraint(
            "structured_field_count IS NULL OR structured_field_count >= 0",
            name="structured_fields_non_negative",
        ),
        Index("ix_ai_review_event_org_type_time", "org_id", "event_type", "occurred_at"),
        Index("ix_ai_review_event_org_draft_time", "org_id", "draft_id", "occurred_at"),
        Index(
            "uq_ai_review_event_draft_created",
            "org_id",
            "draft_id",
            unique=True,
            postgresql_where=text("event_type = 'ai_draft_created' AND deleted_at IS NULL"),
            sqlite_where=text("event_type = 'ai_draft_created' AND deleted_at IS NULL"),
        ),
        Index(
            "uq_ai_review_event_draft_terminal",
            "org_id",
            "draft_id",
            unique=True,
            postgresql_where=text(
                "event_type IN ('review_submitted','draft_expired') AND deleted_at IS NULL"
            ),
            sqlite_where=text(
                "event_type IN ('review_submitted','draft_expired') AND deleted_at IS NULL"
            ),
        ),
    )


class AiRejectReason(SystemFieldsMixin, Base):
    """Global reject-reason dictionary; rows use the all-zero org id."""

    __tablename__ = "ai_reject_reason"

    code: Mapped[str] = mapped_column(String(32), nullable=False)
    label_zh: Mapped[str] = mapped_column(String(64), nullable=False)
    label_en: Mapped[str] = mapped_column(String(64), nullable=False)
    requires_note: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (
        UniqueConstraint("org_id", "code", name="uq_ai_reject_reason_org_code"),
        CheckConstraint("sort_order >= 0", name="sort_order_non_negative"),
    )

    @property
    def global_org_id(self) -> uuid.UUID:
        return uuid.UUID(GLOBAL_ORG_ID)
