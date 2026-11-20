"""Pure validation and normalization for review events."""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from app.eval.constants import (
    ACTIONS,
    BATCH_MAX,
    EVENT_DRAFT_CREATED,
    EVENT_DRAFT_EXPIRED,
    EVENT_REVIEW_OPENED,
    EVENT_REVIEW_SUBMITTED,
    EVENT_TYPES,
    FINAL_HASH_LENGTH,
    MAX_FINAL_REF_LENGTH,
    MAX_MODEL_PROFILE_LENGTH,
    MAX_NOTE_LENGTH,
    MAX_PROMPT_VERSION_LENGTH,
    MAX_REVIEW_SECONDS,
    MAX_TOOL_LENGTH,
    REJECT_REASON_CODES,
    REJECT_REASON_OTHER,
    TERMINAL_EVENT_TYPES,
)
from app.eval.errors import ReviewEventError, invalid

_HEX64 = re.compile(r"^[0-9a-f]{64}$")

_ALLOWED_KEYS = {
    "event_id",
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
}


@dataclass(frozen=True)
class NormalizedEvent:
    event_id: uuid.UUID
    event_type: str
    draft_id: uuid.UUID
    occurred_at: datetime
    tool: str | None = None
    scenario: str | None = None
    prompt_version: str | None = None
    model_profile: str | None = None
    output_chars: int | None = None
    structured_field_count: int | None = None
    action: str | None = None
    final_ref: str | None = None
    final_hash: str | None = None
    reviewer_id: uuid.UUID | None = None
    review_seconds: int | None = None
    reject_reason_code: str | None = None
    reject_reason_note: str | None = None

    @property
    def is_terminal(self) -> bool:
        return self.event_type in TERMINAL_EVENT_TYPES

    def payload(self) -> dict[str, Any]:
        return {
            "event_type": self.event_type,
            "draft_id": self.draft_id,
            "occurred_at": self.occurred_at,
            "tool": self.tool,
            "scenario": self.scenario,
            "prompt_version": self.prompt_version,
            "model_profile": self.model_profile,
            "output_chars": self.output_chars,
            "structured_field_count": self.structured_field_count,
            "action": self.action,
            "final_ref": self.final_ref,
            "final_hash": self.final_hash,
            "reviewer_id": self.reviewer_id,
            "review_seconds": self.review_seconds,
            "reject_reason_code": self.reject_reason_code,
            "reject_reason_note": self.reject_reason_note,
        }


def _fail(message: str, code: str = "EVENT_FIELD_INVALID") -> ReviewEventError:
    return invalid(code, message)


def _uuid(value: Any, field: str) -> uuid.UUID:
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        raise _fail(f"{field} must be a UUID") from None


def _text(value: Any, field: str, limit: int, required: bool = False) -> str | None:
    if value is None:
        if required:
            raise _fail(f"{field} is required")
        return None
    if not isinstance(value, str):
        raise _fail(f"{field} must be a string")
    value = value.strip()
    if not value:
        if required:
            raise _fail(f"{field} is required")
        return None
    if len(value) > limit:
        raise _fail(f"{field} must be at most {limit} characters")
    return value


def _integer(value: Any, field: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise _fail(f"{field} must be an integer")
    if value < minimum or value > maximum:
        raise _fail(f"{field} must be between {minimum} and {maximum}")
    return value


def _when(value: Any) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            raise _fail("occurred_at must be an ISO8601 timestamp") from None
    else:
        raise _fail("occurred_at must be an ISO8601 timestamp")
    if parsed.tzinfo is None:
        raise _fail("occurred_at must include a timezone (UTC)")
    return parsed.astimezone(timezone.utc)


def normalize_events(events: Any) -> list[NormalizedEvent]:
    if not isinstance(events, (list, tuple)):
        raise _fail("events must be a list")
    if not events:
        raise invalid("BATCH_EMPTY", "events must contain at least one item")
    if len(events) > BATCH_MAX:
        raise invalid("BATCH_TOO_LARGE", f"a batch may contain at most {BATCH_MAX} events")

    normalized: list[NormalizedEvent] = []
    for index, raw in enumerate(events):
        if not isinstance(raw, dict):
            raise _fail(f"events[{index}] must be an object")
        unknown = set(raw) - _ALLOWED_KEYS
        if unknown:
            raise _fail(f"events[{index}] has unknown fields: {sorted(unknown)}")
        event_id = _uuid(raw.get("event_id"), f"events[{index}].event_id")
        event_type = raw.get("event_type")
        if event_type not in EVENT_TYPES:
            raise _fail(f"events[{index}].event_type is invalid")
        draft_id = _uuid(raw.get("draft_id"), f"events[{index}].draft_id")
        occurred_at = _when(raw.get("occurred_at"))

        tool = _text(raw.get("tool"), "tool", MAX_TOOL_LENGTH)
        scenario = _text(raw.get("scenario"), "scenario", MAX_TOOL_LENGTH)
        prompt_version = _text(
            raw.get("prompt_version"), "prompt_version", MAX_PROMPT_VERSION_LENGTH
        )
        model_profile = _text(
            raw.get("model_profile"), "model_profile", MAX_MODEL_PROFILE_LENGTH
        )
        action = raw.get("action")
        if action is not None and action not in ACTIONS:
            raise _fail("action is invalid")
        final_ref = _text(raw.get("final_ref"), "final_ref", MAX_FINAL_REF_LENGTH)
        final_hash = _text(raw.get("final_hash"), "final_hash", FINAL_HASH_LENGTH)
        reviewer_id = (
            _uuid(raw["reviewer_id"], "reviewer_id") if raw.get("reviewer_id") else None
        )
        review_seconds = raw.get("review_seconds")
        if review_seconds is not None:
            review_seconds = _integer(review_seconds, "review_seconds", 0, MAX_REVIEW_SECONDS)
        output_chars = raw.get("output_chars")
        if output_chars is not None:
            output_chars = _integer(output_chars, "output_chars", 0, 10**9)
        structured_field_count = raw.get("structured_field_count")
        if structured_field_count is not None:
            structured_field_count = _integer(
                structured_field_count, "structured_field_count", 0, 10**6
            )
        reason = raw.get("reject_reason_code")
        if reason is not None and reason not in REJECT_REASON_CODES:
            raise invalid("REJECT_REASON_INVALID", "reject_reason_code is not in the dictionary")
        note = _text(raw.get("reject_reason_note"), "reject_reason_note", MAX_NOTE_LENGTH)

        if event_type == EVENT_DRAFT_CREATED:
            if tool is None or scenario is None or prompt_version is None:
                raise _fail("ai_draft_created requires tool, scenario and prompt_version")
            if output_chars is None or structured_field_count is None:
                raise _fail("ai_draft_created requires output_chars and structured_field_count")
            if action or final_ref or final_hash or reviewer_id or review_seconds or reason or note:
                raise _fail("ai_draft_created must not carry review result fields")
        elif event_type == EVENT_REVIEW_OPENED:
            if reviewer_id is None:
                raise _fail("review_opened requires reviewer_id")
            if action or final_ref or final_hash or review_seconds or reason or note:
                raise _fail("review_opened must not carry review result fields")
        elif event_type == EVENT_REVIEW_SUBMITTED:
            if any(
                value is not None
                for value in (tool, scenario, prompt_version, model_profile, output_chars, structured_field_count)
            ):
                raise _fail("review_submitted must not carry draft generation fields")
            if action is None or reviewer_id is None or final_ref is None or final_hash is None:
                raise _fail("review_submitted requires action, reviewer_id, final_ref and final_hash")
            if review_seconds is None:
                raise _fail("review_submitted requires review_seconds")
            if not _HEX64.match(final_hash or ""):
                raise _fail("final_hash must be 64 lowercase hexadecimal characters")
            if action == "rejected":
                if reason is None:
                    raise _fail("rejected requires reject_reason_code")
            elif reason is not None:
                raise _fail("reject_reason_code is only allowed for action=rejected")
        elif event_type == EVENT_DRAFT_EXPIRED:
            if any(
                value is not None
                for value in (
                    tool,
                    scenario,
                    prompt_version,
                    model_profile,
                    output_chars,
                    structured_field_count,
                    action,
                    final_ref,
                    final_hash,
                    reviewer_id,
                    review_seconds,
                    reason,
                    note,
                )
            ):
                raise _fail("draft_expired must not carry extra fields")

        if reason == REJECT_REASON_OTHER and not note:
            raise invalid("OTHER_NOTE_REQUIRED", "reject_reason_note is required when code is other")
        if reason != REJECT_REASON_OTHER and note is not None:
            raise _fail("reject_reason_note is only allowed when code is other")

        normalized.append(
            NormalizedEvent(
                event_id=event_id,
                event_type=event_type,
                draft_id=draft_id,
                occurred_at=occurred_at,
                tool=tool,
                scenario=scenario,
                prompt_version=prompt_version,
                model_profile=model_profile,
                output_chars=output_chars,
                structured_field_count=structured_field_count,
                action=action,
                final_ref=final_ref,
                final_hash=final_hash,
                reviewer_id=reviewer_id,
                review_seconds=review_seconds,
                reject_reason_code=reason,
                reject_reason_note=note,
            )
        )
    return normalized
