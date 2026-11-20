from __future__ import annotations

from alembic import command
from sqlalchemy import inspect, select

from app.eval.dictionaries import seed_reject_reasons
from app.eval.models import AiRejectReason


def test_tables_and_columns_exist(engine):
    inspector = inspect(engine)
    assert {"ai_review_event", "ai_reject_reason"} <= set(inspector.get_table_names())

    event_columns = {column["name"] for column in inspector.get_columns("ai_review_event")}
    expected = {
        "id",
        "org_id",
        "site_id",
        "event_type",
        "tool",
        "scenario",
        "draft_id",
        "prompt_version",
        "model_profile",
        "output_chars",
        "structured_field_count",
        "action",
        "final_ref",
        "final_hash",
        "reviewer_id",
        "review_seconds",
        "reject_reason_code",
        "reject_reason_note",
        "occurred_at",
        "received_at",
        "created_at",
        "created_by",
        "updated_at",
        "deleted_at",
    }
    assert expected <= event_columns
    assert "draft_text" not in event_columns
    assert "final_text" not in event_columns


def test_indexes_exist(engine):
    names = {index["name"] for index in inspect(engine).get_indexes("ai_review_event")}
    assert {
        "ix_ai_review_event_org_type_time",
        "ix_ai_review_event_org_draft_time",
        "uq_ai_review_event_draft_created",
        "uq_ai_review_event_draft_terminal",
    } <= names


def test_dictionary_is_seeded(engine, session):
    reasons = session.scalars(select(AiRejectReason).order_by(AiRejectReason.sort_order)).all()
    assert len(reasons) == 7
    assert [reason.code for reason in reasons] == [
        "factual_error",
        "off_tone",
        "missing_info",
        "policy_violation",
        "duplicate",
        "not_needed",
        "other",
    ]
    other = next(reason for reason in reasons if reason.code == "other")
    assert other.requires_note is True
    assert other.label_zh == "其他"
    assert seed_reject_reasons(session) == 0


def test_alembic_check_has_no_drift(alembic_config, engine):
    command.check(alembic_config)
