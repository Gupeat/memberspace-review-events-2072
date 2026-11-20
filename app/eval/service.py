"""Application service for review-event ingestion.

The service owns batch semantics: validation, dictionary checks, ordering,
idempotency, draft state transitions and per-item savepoints. Callers get a
single commit per batch; any domain error rolls the whole batch back.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.eval.constants import (
    EVENT_DRAFT_CREATED,
    EVENT_DRAFT_EXPIRED,
    EVENT_REVIEW_OPENED,
    EVENT_REVIEW_SUBMITTED,
    EXPIRY_DAYS,
    GLOBAL_ORG_ID,
)
from app.eval.errors import ReviewEventError, conflict, invalid
from app.eval.models import AiRejectReason, AiReviewEvent
from app.eval.validators import NormalizedEvent, normalize_events

_ORDER = {
    EVENT_DRAFT_CREATED: 0,
    EVENT_REVIEW_OPENED: 1,
    EVENT_REVIEW_SUBMITTED: 2,
    EVENT_DRAFT_EXPIRED: 2,
}
_GLOBAL_ORG = uuid.UUID(GLOBAL_ORG_ID)
_FINGERPRINT_FIELDS = (
    "event_type",
    "draft_id",
    "occurred_at",
    "tool",
    "scenario",
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
)


@dataclass
class BatchItem:
    event_id: uuid.UUID
    status: str

    def as_dict(self) -> dict[str, str]:
        return {"event_id": str(self.event_id), "status": self.status}


@dataclass
class BatchResult:
    created: int = 0
    duplicates: int = 0
    items: list[BatchItem] = field(default_factory=list)

    @property
    def received(self) -> int:
        return self.created + self.duplicates

    def as_dict(self) -> dict[str, Any]:
        return {
            "created": self.created,
            "duplicates": self.duplicates,
            "received": self.received,
            "items": [item.as_dict() for item in self.items],
        }


def _ensure_physical_transaction(session: Session) -> None:
    """Start a real SQLite transaction before the first SAVEPOINT.

    SQLite commits the outermost SAVEPOINT when it is released. Without an
    explicit BEGIN, the first per-item savepoint would commit its own insert
    and a later batch error could no longer roll the batch back. PostgreSQL
    already has a physical transaction at this point, so it is untouched.
    """
    if session.get_bind().dialect.name != "sqlite":
        return
    connection = session.connection()
    dbapi = connection.connection.dbapi_connection
    if dbapi is not None and not getattr(dbapi, "in_transaction", True):
        session.execute(text("BEGIN"))


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def fingerprint(event: NormalizedEvent) -> tuple[Any, ...]:
    return (
        event.event_type,
        event.draft_id,
        _utc(event.occurred_at),
        event.tool,
        event.scenario,
        event.prompt_version,
        event.model_profile,
        event.output_chars,
        event.structured_field_count,
        event.action,
        event.final_ref,
        event.final_hash,
        event.reviewer_id,
        event.review_seconds,
        event.reject_reason_code,
        event.reject_reason_note,
    )


def _row_fingerprint(row: AiReviewEvent) -> tuple[Any, ...]:
    return (
        row.event_type,
        row.draft_id,
        _utc(row.occurred_at),
        row.tool,
        row.scenario,
        row.prompt_version,
        row.model_profile,
        row.output_chars,
        row.structured_field_count,
        row.action,
        row.final_ref,
        row.final_hash,
        row.reviewer_id,
        row.review_seconds,
        row.reject_reason_code,
        row.reject_reason_note,
    )


def _event_row(event: NormalizedEvent, org_id: uuid.UUID, actor_id: uuid.UUID | None) -> AiReviewEvent:
    return AiReviewEvent(
        id=event.event_id,
        org_id=org_id,
        event_type=event.event_type,
        draft_id=event.draft_id,
        occurred_at=event.occurred_at,
        tool=event.tool,
        scenario=event.scenario,
        prompt_version=event.prompt_version,
        model_profile=event.model_profile,
        output_chars=event.output_chars,
        structured_field_count=event.structured_field_count,
        action=event.action,
        final_ref=event.final_ref,
        final_hash=event.final_hash,
        reviewer_id=event.reviewer_id,
        review_seconds=event.review_seconds,
        reject_reason_code=event.reject_reason_code,
        reject_reason_note=event.reject_reason_note,
        created_by=actor_id,
    )


def _active_reasons(session: Session) -> set[str]:
    rows = session.execute(
        select(AiRejectReason.code).where(
            AiRejectReason.org_id == _GLOBAL_ORG,
            AiRejectReason.active.is_(True),
        )
    ).scalars()
    return set(rows)


def _validate_dictionary(session: Session, events: Iterable[NormalizedEvent]) -> None:
    active = _active_reasons(session)
    for event in events:
        code = event.reject_reason_code
        if code is not None and code not in active:
            raise invalid("REJECT_REASON_INVALID", f"reject_reason_code {code!r} is not active")


def _find_created(session: Session, org_id: uuid.UUID, draft_id: uuid.UUID) -> AiReviewEvent | None:
    return session.execute(
        select(AiReviewEvent).where(
            AiReviewEvent.org_id == org_id,
            AiReviewEvent.draft_id == draft_id,
            AiReviewEvent.event_type == EVENT_DRAFT_CREATED,
            AiReviewEvent.deleted_at.is_(None),
        )
    ).scalar_one_or_none()


def _latest_opened(session: Session, org_id: uuid.UUID, draft_id: uuid.UUID) -> datetime | None:
    return session.scalar(
        select(func.max(AiReviewEvent.occurred_at)).where(
            AiReviewEvent.org_id == org_id,
            AiReviewEvent.draft_id == draft_id,
            AiReviewEvent.event_type == EVENT_REVIEW_OPENED,
            AiReviewEvent.deleted_at.is_(None),
        )
    )


def _find_terminal(session: Session, org_id: uuid.UUID, draft_id: uuid.UUID) -> AiReviewEvent | None:
    return session.execute(
        select(AiReviewEvent).where(
            AiReviewEvent.org_id == org_id,
            AiReviewEvent.draft_id == draft_id,
            AiReviewEvent.event_type.in_((EVENT_REVIEW_SUBMITTED, EVENT_DRAFT_EXPIRED)),
            AiReviewEvent.deleted_at.is_(None),
        )
    ).scalar_one_or_none()


def _classify_integrity_error(
    session: Session, event: NormalizedEvent, org_id: uuid.UUID
) -> ReviewEventError:
    with session.no_autoflush:
        existing = session.get(AiReviewEvent, event.event_id)
        if existing is not None:
            if existing.org_id != org_id:
                return conflict("EVENT_ID_CONFLICT", "event_id is already used by another tenant")
            return conflict(
                "EVENT_ID_PAYLOAD_MISMATCH", "event_id already exists with different payload"
            )
        if event.event_type == EVENT_DRAFT_CREATED and _find_created(session, org_id, event.draft_id):
            return conflict("DRAFT_ALREADY_EXISTS", "draft already has an ai_draft_created event")
        if event.is_terminal and _find_terminal(session, org_id, event.draft_id):
            return conflict("DRAFT_ALREADY_TERMINAL", "draft already has a terminal event")
    return invalid("EVENT_PERSISTENCE_CONFLICT", "event could not be stored")


def app_events(events: list[dict[str, Any]], *, org_id: uuid.UUID) -> list[dict[str, Any]]:
    """Convenience helper for callers that only need normalized dicts."""
    return [
        {**event.payload(), "event_id": event.event_id, "org_id": org_id}
        for event in normalize_events(events)
    ]


def submit_review_events(
    session: Session,
    org_id: uuid.UUID,
    events: Iterable[dict[str, Any]],
    actor_id: uuid.UUID | None = None,
) -> BatchResult:
    """Validate and persist one batch of review events.

    The whole batch is atomic: a domain error rolls back every item and
    raises ReviewEventError with an HTTP-compatible status code.
    """
    normalized = normalize_events(events)
    _validate_dictionary(session, normalized)
    _ensure_physical_transaction(session)

    # Same-batch idempotency and conflict detection.
    seen: dict[uuid.UUID, tuple[Any, ...]] = {}
    duplicate_ids: set[uuid.UUID] = set()
    created_drafts: set[uuid.UUID] = set()
    terminal_drafts: set[uuid.UUID] = set()
    for event in normalized:
        prior = seen.get(event.event_id)
        if prior is not None:
            if prior != fingerprint(event):
                raise conflict(
                    "EVENT_ID_PAYLOAD_MISMATCH",
                    f"event_id {event.event_id} appears more than once with different payloads",
                )
            duplicate_ids.add(event.event_id)
            continue
        seen[event.event_id] = fingerprint(event)
        if event.event_type == EVENT_DRAFT_CREATED:
            if event.draft_id in created_drafts:
                raise conflict("DRAFT_ALREADY_EXISTS", f"draft {event.draft_id} has two creation events")
            created_drafts.add(event.draft_id)
        elif event.is_terminal:
            if event.draft_id in terminal_drafts:
                raise conflict(
                    "DRAFT_ALREADY_TERMINAL", f"draft {event.draft_id} has two terminal events"
                )
            terminal_drafts.add(event.draft_id)

    indexed = list(enumerate(normalized))
    indexed.sort(key=lambda pair: (_ORDER.get(pair[1].event_type, 9), _utc(pair[1].occurred_at), pair[0]))
    items: dict[int, BatchItem] = {}
    opened_by_draft: dict[uuid.UUID, datetime] = {}

    try:
        for index, event in indexed:
            if event.event_id in duplicate_ids and event.event_id in items:
                items[index] = BatchItem(event.event_id, "duplicate")
                continue
            if event.event_id in duplicate_ids and event.event_id not in items:
                # First occurrence of a same-batch duplicate is still processed.
                pass

            existing = session.get(AiReviewEvent, event.event_id)
            if existing is not None:
                if existing.org_id != org_id:
                    raise conflict(
                        "EVENT_ID_CONFLICT",
                        f"event_id {event.event_id} is already used by another tenant",
                    )
                if _row_fingerprint(existing) != fingerprint(event):
                    raise conflict(
                        "EVENT_ID_PAYLOAD_MISMATCH",
                        f"event_id {event.event_id} already exists with a different payload",
                    )
                items[index] = BatchItem(event.event_id, "duplicate")
                continue

            created = None
            if event.event_type != EVENT_DRAFT_CREATED:
                created = _find_created(session, org_id, event.draft_id)
                if created is None:
                    raise invalid(
                        "DRAFT_NOT_FOUND",
                        f"draft {event.draft_id} has no ai_draft_created event",
                    )
                if _utc(event.occurred_at) < _utc(created.occurred_at):
                    raise invalid(
                        "EVENT_BEFORE_DRAFT_CREATED",
                        f"event {event.event_id} occurs before the draft creation event",
                    )
            if event.event_type == EVENT_DRAFT_CREATED:
                if _find_created(session, org_id, event.draft_id) is not None:
                    raise conflict(
                        "DRAFT_ALREADY_EXISTS", f"draft {event.draft_id} already has a creation event"
                    )
            if event.is_terminal:
                if _find_terminal(session, org_id, event.draft_id) is not None:
                    raise conflict(
                        "DRAFT_ALREADY_TERMINAL", f"draft {event.draft_id} already has a terminal event"
                    )
                opened_at = opened_by_draft.get(event.draft_id)
                if opened_at is None:
                    opened_at = _latest_opened(session, org_id, event.draft_id)
                if opened_at is not None and _utc(event.occurred_at) < _utc(opened_at):
                    raise invalid(
                        "EVENT_BEFORE_REVIEW_OPENED",
                        f"event {event.event_id} occurs before the latest review_opened event",
                    )
                if event.event_type == EVENT_DRAFT_EXPIRED:
                    assert created is not None
                    elapsed = _utc(event.occurred_at) - _utc(created.occurred_at)
                    if elapsed < timedelta(days=EXPIRY_DAYS):
                        raise invalid(
                            "DRAFT_NOT_EXPIRED",
                            f"draft {event.draft_id} expires only after {EXPIRY_DAYS} days",
                        )
            elif event.event_type in (EVENT_REVIEW_OPENED, EVENT_REVIEW_SUBMITTED):
                if _find_terminal(session, org_id, event.draft_id) is not None:
                    raise conflict(
                        "DRAFT_ALREADY_TERMINAL",
                        f"draft {event.draft_id} is already closed by a terminal event",
                    )
                if event.event_type == EVENT_REVIEW_OPENED:
                    previous = opened_by_draft.get(event.draft_id)
                    if previous is None or _utc(event.occurred_at) > _utc(previous):
                        opened_by_draft[event.draft_id] = event.occurred_at

            try:
                with session.begin_nested():
                    session.add(_event_row(event, org_id, actor_id))
                    session.flush()
            except IntegrityError:
                # A concurrent caller may have inserted the same event_id with
                # the same payload after our pre-check. Treat that as the
                # idempotent duplicate it is; every other conflict is an error.
                with session.no_autoflush:
                    existing = session.get(AiReviewEvent, event.event_id)
                if (
                    existing is not None
                    and existing.org_id == org_id
                    and _row_fingerprint(existing) == fingerprint(event)
                ):
                    items[index] = BatchItem(event.event_id, "duplicate")
                    continue
                raise _classify_integrity_error(session, event, org_id) from None
            items[index] = BatchItem(event.event_id, "created")

        session.commit()
    except ReviewEventError:
        session.rollback()
        raise
    except IntegrityError:
        session.rollback()
        raise
    except Exception:
        session.rollback()
        raise

    ordered = [items[index] for index in range(len(normalized))]
    created_count = sum(1 for item in ordered if item.status == "created")
    duplicate_count = sum(1 for item in ordered if item.status == "duplicate")
    return BatchResult(created=created_count, duplicates=duplicate_count, items=ordered)


def _expired_event_id(org_id: uuid.UUID, draft_id: uuid.UUID) -> uuid.UUID:
    return uuid.uuid5(uuid.NAMESPACE_URL, f"review-event:draft-expired:{org_id}:{draft_id}")


def expire_stale_drafts(
    session: Session, org_id: uuid.UUID, now: datetime | None = None
) -> list[uuid.UUID]:
    """Emit one deterministic draft_expired event per stale draft."""
    now = _utc(now or datetime.now(timezone.utc))
    _ensure_physical_transaction(session)
    cutoff = now - timedelta(days=EXPIRY_DAYS)
    created_rows = list(
        session.execute(
            select(AiReviewEvent).where(
                AiReviewEvent.org_id == org_id,
                AiReviewEvent.event_type == EVENT_DRAFT_CREATED,
                AiReviewEvent.deleted_at.is_(None),
                AiReviewEvent.occurred_at <= cutoff,
            )
        ).scalars()
    )
    emitted: list[uuid.UUID] = []
    try:
        for created in created_rows:
            if _find_terminal(session, org_id, created.draft_id) is not None:
                continue
            event_id = _expired_event_id(org_id, created.draft_id)
            if session.get(AiReviewEvent, event_id) is not None:
                continue
            row = AiReviewEvent(
                id=event_id,
                org_id=org_id,
                event_type=EVENT_DRAFT_EXPIRED,
                draft_id=created.draft_id,
                occurred_at=now,
            )
            try:
                with session.begin_nested():
                    session.add(row)
                    session.flush()
            except IntegrityError:
                # The savepoint is already rolled back; do not roll back the
                # whole batch, otherwise previously emitted expiry events would
                # be lost while still reported in the returned list.
                if _find_terminal(session, org_id, created.draft_id) is None:
                    raise
                continue
            emitted.append(event_id)
        session.commit()
    except Exception:
        session.rollback()
        raise
    return emitted
