from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import insert
from sqlalchemy.exc import IntegrityError

from app.eval.models import AiReviewEvent
from tests.factories import (
    DRAFT,
    ORG_B,
    draft_row,
    expired_row,
    opened_row,
    submitted_row,
)


def _insert(session, row):
    session.execute(insert(AiReviewEvent).values(**row))
    session.commit()


def _reject(session, row):
    with pytest.raises(IntegrityError):
        session.execute(insert(AiReviewEvent).values(**row))
        session.commit()
    session.rollback()


def test_raw_insert_accepts_draft_and_review(session):
    _insert(session, draft_row())
    _insert(session, opened_row())
    _insert(session, submitted_row())
    assert session.query(AiReviewEvent).count() == 3


def test_event_type_check_rejects_unknown_value(session):
    row = draft_row(event_type="bogus")
    _reject(session, row)


def test_only_one_active_draft_created_per_org_and_draft(session):
    _insert(session, draft_row())
    _reject(session, draft_row())


def test_same_draft_allowed_in_another_org(session):
    _insert(session, draft_row())
    _insert(session, draft_row(org_id=ORG_B))
    assert session.query(AiReviewEvent).count() == 2


def test_soft_deleted_draft_allows_reinsert(session):
    _insert(session, draft_row())
    session.execute(
        AiReviewEvent.__table__.update()
        .where(AiReviewEvent.draft_id == DRAFT)
        .values(deleted_at=datetime(2026, 11, 2, tzinfo=timezone.utc))
    )
    session.commit()
    _insert(session, draft_row())
    assert session.query(AiReviewEvent).count() == 2


def test_second_terminal_event_is_rejected(session):
    _insert(session, draft_row())
    _insert(session, submitted_row())
    _reject(session, expired_row())


def test_expiry_then_review_is_rejected(session):
    _insert(session, draft_row())
    _insert(session, expired_row())
    _reject(session, submitted_row())


def test_rejected_requires_reason_code(session):
    _insert(session, draft_row())
    _reject(session, submitted_row(action="rejected", reject_reason_code=None))


def test_other_reason_requires_note(session):
    _insert(session, draft_row())
    _reject(session, submitted_row(action="rejected", reject_reason_code="other"))


def test_note_is_only_allowed_for_other(session):
    _insert(session, draft_row())
    _reject(
        session,
        submitted_row(
            action="rejected",
            reject_reason_code="factual_error",
            reject_reason_note="not allowed",
        ),
    )


def test_reason_code_is_only_allowed_when_rejected(session):
    _insert(session, draft_row())
    _reject(session, submitted_row(action="adopted_as_is", reject_reason_code="factual_error"))


def test_final_hash_must_be_64_chars(session):
    _insert(session, draft_row())
    _reject(session, submitted_row(final_hash="abc"))


def test_review_seconds_range(session):
    _insert(session, draft_row())
    _reject(session, submitted_row(review_seconds=99999))


def test_draft_created_requires_generation_metadata(session):
    _reject(session, draft_row(output_chars=None))
