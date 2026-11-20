from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from app.eval.constants import EVENT_DRAFT_CREATED, EVENT_DRAFT_EXPIRED, EVENT_REVIEW_SUBMITTED
from app.eval.dictionaries import get_reason
from app.eval.errors import ReviewEventError
from app.eval.models import AiReviewEvent
from app.eval.service import expire_stale_drafts, submit_review_events
from tests.factories import (
    BASE_TIME,
    DRAFT,
    ORG_A,
    REVIEWER,
    draft_row,
    expired_row,
    opened_row,
    submitted_row,
)


def api_event(row, event_id=None):
    event = dict(row)
    original_id = event.pop("id")
    event.pop("org_id", None)
    event.pop("site_id", None)
    event.pop("created_by", None)
    event["event_id"] = str(event_id or original_id)
    event["occurred_at"] = event["occurred_at"].isoformat()
    for key, value in list(event.items()):
        if isinstance(value, uuid.UUID):
            event[key] = str(value)
    return event


def count_events(session):
    return session.scalar(select(func.count()).select_from(AiReviewEvent))


def expect_error(session, events, code, status=422):
    with pytest.raises(ReviewEventError) as caught:
        submit_review_events(session, ORG_A, events)
    assert caught.value.code == code
    assert caught.value.status_code == status
    session.rollback()
    return caught.value


def test_ac1_101_events_are_rejected(session):
    events = [
        api_event(draft_row(id=uuid.uuid4(), draft_id=uuid.uuid4())) for _ in range(101)
    ]
    expect_error(session, events, "BATCH_TOO_LARGE")
    assert count_events(session) == 0


def test_ac1_100_events_are_persisted(session):
    events = [
        api_event(draft_row(id=uuid.uuid4(), draft_id=uuid.uuid4())) for _ in range(100)
    ]
    result = submit_review_events(session, ORG_A, events)
    assert result.created == 100
    assert result.duplicates == 0
    assert result.received == 100
    assert count_events(session) == 100


def test_ac2_same_event_id_is_written_once(session):
    row = draft_row()
    event = api_event(row)
    result = submit_review_events(session, ORG_A, [event])
    assert result.created == 1
    again = submit_review_events(session, ORG_A, [event])
    assert again.created == 0
    assert again.duplicates == 1
    assert count_events(session) == 1


def test_same_event_id_with_different_payload_conflicts(session):
    row = draft_row()
    event = api_event(row)
    submit_review_events(session, ORG_A, [event])
    changed = dict(event)
    changed["scenario"] = "another_scenario"
    expect_error(session, [changed], "EVENT_ID_PAYLOAD_MISMATCH", 409)
    assert count_events(session) == 1


def test_same_batch_duplicate_is_collapsed(session):
    event = api_event(draft_row())
    result = submit_review_events(session, ORG_A, [event, event])
    assert result.created == 1
    assert result.duplicates == 1
    assert count_events(session) == 1


def test_same_batch_duplicate_with_different_payload_conflicts(session):
    event = api_event(draft_row())
    changed = dict(event)
    changed["tool"] = "another_tool"
    expect_error(session, [event, changed], "EVENT_ID_PAYLOAD_MISMATCH", 409)


def test_ac3_second_terminal_event_conflicts(session):
    submit_review_events(session, ORG_A, [api_event(draft_row())])
    submit_review_events(session, ORG_A, [api_event(submitted_row())])
    expect_error(session, [api_event(expired_row())], "DRAFT_ALREADY_TERMINAL", 409)
    assert count_events(session) == 2


def test_two_terminal_events_in_one_batch_conflict(session):
    events = [api_event(draft_row()), api_event(submitted_row()), api_event(expired_row())]
    expect_error(session, events, "DRAFT_ALREADY_TERMINAL", 409)
    assert count_events(session) == 0


def test_two_creation_events_in_one_batch_conflict(session):
    events = [api_event(draft_row(id=uuid.uuid4())) for _ in range(2)]
    expect_error(session, events, "DRAFT_ALREADY_EXISTS", 409)
    assert count_events(session) == 0


def test_second_creation_event_conflicts(session):
    submit_review_events(session, ORG_A, [api_event(draft_row())])
    expect_error(session, [api_event(draft_row(id=uuid.uuid4()))], "DRAFT_ALREADY_EXISTS", 409)


def test_ac4_other_requires_note(session):
    row = submitted_row("rejected")
    row["reject_reason_code"] = "other"
    row.pop("reject_reason_note", None)
    expect_error(session, [api_event(row)], "OTHER_NOTE_REQUIRED")
    assert count_events(session) == 0


def test_other_with_note_is_accepted(session):
    submit_review_events(session, ORG_A, [api_event(draft_row())])
    row = submitted_row("rejected")
    row["reject_reason_code"] = "other"
    row["reject_reason_note"] = "需要人工补充行业背景"
    result = submit_review_events(session, ORG_A, [api_event(row)])
    assert result.created == 1


def test_note_is_rejected_for_other_codes(session):
    submit_review_events(session, ORG_A, [api_event(draft_row())])
    row = submitted_row("rejected")
    row["reject_reason_code"] = "factual_error"
    row["reject_reason_note"] = "unexpected"
    expect_error(session, [api_event(row)], "EVENT_FIELD_INVALID")


def test_inactive_reason_is_rejected(session):
    submit_review_events(session, ORG_A, [api_event(draft_row())])
    reason = get_reason(session, "factual_error")
    reason.active = False
    session.commit()
    expect_error(session, [api_event(submitted_row("rejected"))], "REJECT_REASON_INVALID")


def test_review_requires_existing_draft(session):
    expect_error(session, [api_event(opened_row())], "DRAFT_NOT_FOUND")


def test_review_cannot_precede_draft_creation(session):
    submit_review_events(session, ORG_A, [api_event(draft_row())])
    early = submitted_row()
    early["occurred_at"] = BASE_TIME - timedelta(hours=1)
    expect_error(session, [api_event(early)], "EVENT_BEFORE_DRAFT_CREATED")


def test_batch_is_ordered_by_event_type(session):
    # Caller sends terminal, opened and creation events in reverse order.
    events = [api_event(submitted_row()), api_event(opened_row()), api_event(draft_row())]
    result = submit_review_events(session, ORG_A, events)
    assert result.created == 3
    assert count_events(session) == 3
    rows = session.scalars(select(AiReviewEvent).order_by(AiReviewEvent.occurred_at)).all()
    assert [row.event_type for row in rows] == [
        EVENT_DRAFT_CREATED,
        "review_opened",
        EVENT_REVIEW_SUBMITTED,
    ]


def test_terminal_cannot_precede_opened_in_same_batch(session):
    early = submitted_row()
    early["occurred_at"] = BASE_TIME + timedelta(minutes=30)
    events = [api_event(draft_row()), api_event(opened_row()), api_event(early)]
    expect_error(session, events, "EVENT_BEFORE_REVIEW_OPENED")
    assert count_events(session) == 0


def test_terminal_cannot_precede_existing_opened(session):
    submit_review_events(session, ORG_A, [api_event(draft_row()), api_event(opened_row())])
    early = submitted_row()
    early["occurred_at"] = BASE_TIME + timedelta(minutes=30)
    expect_error(session, [api_event(early)], "EVENT_BEFORE_REVIEW_OPENED")
    assert count_events(session) == 2


def test_expired_event_must_be_seven_days_late(session):
    submit_review_events(session, ORG_A, [api_event(draft_row())])
    early = expired_row()
    early["occurred_at"] = BASE_TIME + timedelta(days=6)
    expect_error(session, [api_event(early)], "DRAFT_NOT_EXPIRED")
    assert count_events(session) == 1


def test_batch_is_atomic(session):
    good = api_event(draft_row(id=uuid.uuid4(), draft_id=uuid.uuid4()))
    bad = api_event(submitted_row())
    bad["final_hash"] = "not-a-hash"
    expect_error(session, [good, bad], "EVENT_FIELD_INVALID")
    assert count_events(session) == 0


def test_batch_rolls_back_after_a_write(session):
    good = api_event(draft_row(id=uuid.uuid4(), draft_id=uuid.uuid4()))
    # A different, unknown draft: the creation above is already written and
    # must be rolled back when this item fails.
    bad = api_event(opened_row(id=uuid.uuid4(), draft_id=uuid.uuid4()))
    expect_error(session, [good, bad], "DRAFT_NOT_FOUND")
    assert count_events(session) == 0


def test_review_after_terminal_conflicts(session):
    submit_review_events(session, ORG_A, [api_event(draft_row())])
    submit_review_events(session, ORG_A, [api_event(submitted_row())])
    expect_error(session, [api_event(opened_row(id=uuid.uuid4()))], "DRAFT_ALREADY_TERMINAL", 409)


def test_expire_stale_drafts_is_deterministic_and_idempotent(session):
    submit_review_events(session, ORG_A, [api_event(draft_row())])
    now = BASE_TIME + timedelta(days=8)
    emitted = expire_stale_drafts(session, ORG_A, now=now)
    assert len(emitted) == 1
    row = session.get(AiReviewEvent, emitted[0])
    assert row is not None
    assert row.event_type == EVENT_DRAFT_EXPIRED
    assert row.draft_id == DRAFT
    assert expire_stale_drafts(session, ORG_A, now=now + timedelta(hours=1)) == []
    assert count_events(session) == 2


def test_expire_stale_drafts_skips_terminal_drafts(session):
    submit_review_events(
        session,
        ORG_A,
        [api_event(draft_row()), api_event(submitted_row())],
    )
    assert expire_stale_drafts(session, ORG_A, now=BASE_TIME + timedelta(days=8)) == []
    assert count_events(session) == 2


def test_event_id_cannot_be_reused_across_tenants(session):
    event = api_event(draft_row())
    submit_review_events(session, ORG_A, [event])
    other_org = uuid.UUID(int=8999)
    with pytest.raises(ReviewEventError) as caught:
        submit_review_events(session, other_org, [event])
    assert caught.value.code == "EVENT_ID_CONFLICT"
    assert caught.value.status_code == 409
    assert count_events(session) == 1


def test_org_isolation(session):
    other_org = uuid.UUID(int=8999)
    submit_review_events(session, ORG_A, [api_event(draft_row())])
    opened = submit_review_events(session, ORG_A, [api_event(opened_row())])
    assert opened.created == 1
    # The same draft id under another org has no creation event.
    with pytest.raises(ReviewEventError) as caught:
        submit_review_events(session, other_org, [api_event(submitted_row())])
    assert caught.value.code == "DRAFT_NOT_FOUND"
    assert count_events(session) == 2
