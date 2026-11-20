from __future__ import annotations

import uuid
from datetime import datetime, timezone

from app.eval.constants import GLOBAL_ORG_ID

ORG_A = uuid.UUID(int=8001)
ORG_B = uuid.UUID(int=8002)
SITE = uuid.UUID(int=8003)
ACTOR = uuid.UUID(int=8004)
REVIEWER = uuid.UUID(int=8005)
DRAFT = uuid.UUID(int=8100)

BASE_TIME = datetime(2026, 11, 1, 10, 0, tzinfo=timezone.utc)
HASH = "a" * 64


def base_row(event_type: str, **overrides):
    row = {
        "id": uuid.uuid4(),
        "org_id": ORG_A,
        "site_id": SITE,
        "event_type": event_type,
        "draft_id": DRAFT,
        "occurred_at": BASE_TIME,
        "created_by": ACTOR,
    }
    row.update(overrides)
    return row


def draft_row(**overrides):
    row = base_row(
        "ai_draft_created",
        tool="sop_writer",
        scenario="sop_draft",
        prompt_version="p1",
        model_profile="default",
        output_chars=1200,
        structured_field_count=8,
    )
    row.update(overrides)
    return row


def opened_row(**overrides):
    row = base_row(
        "review_opened",
        reviewer_id=REVIEWER,
        occurred_at=datetime(2026, 11, 1, 11, 0, tzinfo=timezone.utc),
    )
    row.update(overrides)
    return row


def submitted_row(action: str = "adopted_as_is", **overrides):
    row = base_row(
        "review_submitted",
        action=action,
        final_ref="contracts/draft-8100/final.md",
        final_hash=HASH,
        reviewer_id=REVIEWER,
        review_seconds=90,
        occurred_at=datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc),
    )
    if action == "rejected":
        row["reject_reason_code"] = "factual_error"
    row.update(overrides)
    return row


def expired_row(**overrides):
    row = base_row(
        "draft_expired",
        occurred_at=datetime(2026, 11, 9, 10, 0, tzinfo=timezone.utc),
    )
    row.update(overrides)
    return row
