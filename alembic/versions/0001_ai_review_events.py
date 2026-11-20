"""AI review events and reject-reason dictionary.

Revision ID: 0001_ai_review_events
Revises:
Create Date: 2026-11-20
"""
from __future__ import annotations

import uuid

import sqlalchemy as sa
from alembic import op

revision = "0001_ai_review_events"
down_revision = None
branch_labels = None
depends_on = None

ZERO_ORG = uuid.UUID("00000000-0000-0000-0000-000000000000")

REASONS = [
    (7001001, "factual_error", "事实错误", "Factual error", False, 10),
    (7001002, "off_tone", "语气不符", "Off tone", False, 20),
    (7001003, "missing_info", "信息缺失", "Missing information", False, 30),
    (7001004, "policy_violation", "违反规范", "Policy violation", False, 40),
    (7001005, "duplicate", "重复", "Duplicate", False, 50),
    (7001006, "not_needed", "不需要", "Not needed", False, 60),
    (7001007, "other", "其他", "Other", True, 70),
]


def upgrade() -> None:
    op.create_table(
        "ai_reject_reason",
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("label_zh", sa.String(length=64), nullable=False),
        sa.Column("label_en", sa.String(length=64), nullable=False),
        sa.Column("requires_note", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("site_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ai_reject_reason")),
        sa.UniqueConstraint("org_id", "code", name=op.f("uq_ai_reject_reason_org_code")),
        sa.CheckConstraint("sort_order >= 0", name=op.f("ck_ai_reject_reason_sort_order_non_negative")),
    )

    op.create_table(
        "ai_review_event",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("site_id", sa.Uuid(), nullable=True),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("tool", sa.String(length=64), nullable=True),
        sa.Column("scenario", sa.String(length=64), nullable=True),
        sa.Column("draft_id", sa.Uuid(), nullable=False),
        sa.Column("prompt_version", sa.String(length=64), nullable=True),
        sa.Column("model_profile", sa.String(length=64), nullable=True),
        sa.Column("output_chars", sa.Integer(), nullable=True),
        sa.Column("structured_field_count", sa.Integer(), nullable=True),
        sa.Column("action", sa.String(length=32), nullable=True),
        sa.Column("final_ref", sa.String(length=512), nullable=True),
        sa.Column("final_hash", sa.String(length=64), nullable=True),
        sa.Column("reviewer_id", sa.Uuid(), nullable=True),
        sa.Column("review_seconds", sa.Integer(), nullable=True),
        sa.Column("reject_reason_code", sa.String(length=32), nullable=True),
        sa.Column("reject_reason_note", sa.String(length=500), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ai_review_event")),
        sa.CheckConstraint(
            "event_type IN ('ai_draft_created','review_opened','review_submitted','draft_expired')",
            name=op.f("ck_ai_review_event_event_type"),
        ),
        sa.CheckConstraint(
            "action IS NULL OR action IN ('adopted_as_is','adopted_with_edits','rejected')",
            name=op.f("ck_ai_review_event_action"),
        ),
        sa.CheckConstraint(
            "reject_reason_code IS NULL OR reject_reason_code IN "
            "('factual_error','off_tone','missing_info','policy_violation','duplicate','not_needed','other')",
            name=op.f("ck_ai_review_event_reject_reason_code"),
        ),
        sa.CheckConstraint(
            "event_type <> 'ai_draft_created' OR (tool IS NOT NULL AND scenario IS NOT NULL "
            "AND prompt_version IS NOT NULL AND output_chars IS NOT NULL "
            "AND structured_field_count IS NOT NULL)",
            name=op.f("ck_ai_review_event_draft_created_fields"),
        ),
        sa.CheckConstraint(
            "event_type <> 'review_opened' OR reviewer_id IS NOT NULL",
            name=op.f("ck_ai_review_event_review_opened_fields"),
        ),
        sa.CheckConstraint(
            "event_type <> 'review_submitted' OR (action IS NOT NULL AND reviewer_id IS NOT NULL "
            "AND final_ref IS NOT NULL AND final_hash IS NOT NULL AND review_seconds IS NOT NULL)",
            name=op.f("ck_ai_review_event_review_submitted_fields"),
        ),
        sa.CheckConstraint(
            "event_type <> 'review_submitted' OR ((action = 'rejected' AND reject_reason_code IS NOT NULL) "
            "OR (action <> 'rejected' AND reject_reason_code IS NULL))",
            name=op.f("ck_ai_review_event_rejected_requires_reason"),
        ),
        sa.CheckConstraint(
            "reject_reason_code IS NULL OR reject_reason_code <> 'other' OR "
            "(reject_reason_note IS NOT NULL AND length(trim(reject_reason_note)) > 0)",
            name=op.f("ck_ai_review_event_other_requires_note"),
        ),
        sa.CheckConstraint(
            "reject_reason_code = 'other' OR reject_reason_note IS NULL",
            name=op.f("ck_ai_review_event_note_only_for_other"),
        ),
        sa.CheckConstraint(
            "event_type <> 'ai_draft_created' OR (action IS NULL AND final_ref IS NULL "
            "AND final_hash IS NULL AND reviewer_id IS NULL AND review_seconds IS NULL "
            "AND reject_reason_code IS NULL AND reject_reason_note IS NULL)",
            name=op.f("ck_ai_review_event_draft_created_no_review_fields"),
        ),
        sa.CheckConstraint(
            "event_type <> 'review_opened' OR (action IS NULL AND final_ref IS NULL "
            "AND final_hash IS NULL AND review_seconds IS NULL AND reject_reason_code IS NULL "
            "AND reject_reason_note IS NULL)",
            name=op.f("ck_ai_review_event_review_opened_no_result_fields"),
        ),
        sa.CheckConstraint(
            "event_type <> 'review_submitted' OR (tool IS NULL AND scenario IS NULL "
            "AND prompt_version IS NULL AND model_profile IS NULL AND output_chars IS NULL "
            "AND structured_field_count IS NULL)",
            name=op.f("ck_ai_review_event_review_submitted_no_draft_fields"),
        ),
        sa.CheckConstraint(
            "event_type <> 'draft_expired' OR (tool IS NULL AND scenario IS NULL "
            "AND prompt_version IS NULL AND model_profile IS NULL AND output_chars IS NULL "
            "AND structured_field_count IS NULL AND action IS NULL AND final_ref IS NULL "
            "AND final_hash IS NULL AND reviewer_id IS NULL AND review_seconds IS NULL "
            "AND reject_reason_code IS NULL AND reject_reason_note IS NULL)",
            name=op.f("ck_ai_review_event_expired_no_extra_fields"),
        ),
        sa.CheckConstraint(
            "final_hash IS NULL OR length(final_hash) = 64",
            name=op.f("ck_ai_review_event_final_hash_length"),
        ),
        sa.CheckConstraint(
            "review_seconds IS NULL OR (review_seconds >= 0 AND review_seconds <= 86400)",
            name=op.f("ck_ai_review_event_review_seconds_range"),
        ),
        sa.CheckConstraint(
            "output_chars IS NULL OR output_chars >= 0",
            name=op.f("ck_ai_review_event_output_chars_non_negative"),
        ),
        sa.CheckConstraint(
            "structured_field_count IS NULL OR structured_field_count >= 0",
            name=op.f("ck_ai_review_event_structured_fields_non_negative"),
        ),
    )

    op.create_index(
        "ix_ai_review_event_org_type_time",
        "ai_review_event",
        ["org_id", "event_type", "occurred_at"],
    )
    op.create_index(
        "ix_ai_review_event_org_draft_time",
        "ai_review_event",
        ["org_id", "draft_id", "occurred_at"],
    )
    op.create_index(
        "uq_ai_review_event_draft_created",
        "ai_review_event",
        ["org_id", "draft_id"],
        unique=True,
        postgresql_where=sa.text("event_type = 'ai_draft_created' AND deleted_at IS NULL"),
        sqlite_where=sa.text("event_type = 'ai_draft_created' AND deleted_at IS NULL"),
    )
    op.create_index(
        "uq_ai_review_event_draft_terminal",
        "ai_review_event",
        ["org_id", "draft_id"],
        unique=True,
        postgresql_where=sa.text(
            "event_type IN ('review_submitted','draft_expired') AND deleted_at IS NULL"
        ),
        sqlite_where=sa.text(
            "event_type IN ('review_submitted','draft_expired') AND deleted_at IS NULL"
        ),
    )

    reason = sa.table(
        "ai_reject_reason",
        sa.column("id", sa.Uuid()),
        sa.column("org_id", sa.Uuid()),
        sa.column("code", sa.String()),
        sa.column("label_zh", sa.String()),
        sa.column("label_en", sa.String()),
        sa.column("requires_note", sa.Boolean()),
        sa.column("sort_order", sa.Integer()),
        sa.column("active", sa.Boolean()),
    )
    op.bulk_insert(
        reason,
        [
            {
                "id": uuid.UUID(int=rid),
                "org_id": ZERO_ORG,
                "code": code,
                "label_zh": zh,
                "label_en": en,
                "requires_note": requires_note,
                "sort_order": sort_order,
                "active": True,
            }
            for rid, code, zh, en, requires_note, sort_order in REASONS
        ],
    )


def downgrade() -> None:
    op.drop_index("uq_ai_review_event_draft_terminal", table_name="ai_review_event")
    op.drop_index("uq_ai_review_event_draft_created", table_name="ai_review_event")
    op.drop_index("ix_ai_review_event_org_draft_time", table_name="ai_review_event")
    op.drop_index("ix_ai_review_event_org_type_time", table_name="ai_review_event")
    op.drop_table("ai_review_event")
    op.drop_table("ai_reject_reason")
