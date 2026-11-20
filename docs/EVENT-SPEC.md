# Review event specification

Version 1.0 · 2026-11-20

## Purpose

Every AI tool that creates a draft and sends it to a human review queue must
emit the same four events. The events feed adoption rate, edit magnitude,
rejection reasons, review latency and expiry metrics without storing the draft
or final text.

## Event envelope

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| event_id | UUID | yes | Primary key; caller-generated; idempotency key |
| event_type | enum | yes | ai_draft_created, review_opened, review_submitted, draft_expired |
| draft_id | UUID | yes | Stable id of the AI draft |
| occurred_at | ISO8601 with timezone | yes | Business time, normalized to UTC |
| tool | string(64) | creation | e.g. sop_writer |
| scenario | string(64) | creation | e.g. sop_draft |
| prompt_version | string(64) | creation | Prompt or template version |
| model_profile | string(64) | no | Model/routing profile name, no secret |
| output_chars | int >= 0 | creation | Character count, not content |
| structured_field_count | int >= 0 | creation | Number of structured fields |
| action | enum | submitted | adopted_as_is / adopted_with_edits / rejected |
| final_ref | string(512) | submitted | Object-storage or document reference |
| final_hash | 64 hex chars | submitted | SHA-256 of the final content |
| reviewer_id | UUID | opened/submitted | Reviewer identity, no name or email |
| review_seconds | int 0..86400 | submitted | Time spent in review |
| reject_reason_code | enum | rejected | One of the seeded codes |
| reject_reason_note | string(500) | other only | Required for other, forbidden otherwise |

No event stores draft text or final text. The store only keeps `final_ref`
and `final_hash`.

## Event semantics

### ai_draft_created

Emitted exactly once when an AI tool produces a draft. It opens the draft
timeline. A second live creation event for the same (org_id, draft_id) is
rejected by a partial unique index and by the service with
`DRAFT_ALREADY_EXISTS`.

### review_opened

Emitted when a reviewer opens the draft. Requires `reviewer_id`. It must not be
earlier than creation, and it cannot be emitted after a terminal event.

### review_submitted

Emitted exactly once per draft when the reviewer finishes. It is a terminal
event. Requires `action`, `reviewer_id`, `final_ref`, `final_hash` and
`review_seconds`. When `action = rejected`, `reject_reason_code` is required;
`rejected` with `other` also requires a note. A second terminal event returns
HTTP 409 `DRAFT_ALREADY_TERMINAL`.

### draft_expired

Emitted by the expiry job for a draft that still has no terminal event more
than 7 days after creation. Drafts with a `review_opened` event are skipped,
because a reviewer is already handling them. It is a terminal event. The job uses a
deterministic UUID v5 from (org_id, draft_id), so repeated runs and retries are
idempotent. It never deletes the draft.

## State machine

```text
ai_draft_created ──> review_opened ──> review_submitted
        │                                    ▲
        ├──────────── direct submit ─────────┘
        │
        └───────────── > 7 days ────────────> draft_expired
```

`review_opened` is optional; a reviewer may submit directly after creation.
`review_submitted` and `draft_expired` are terminal and mutually exclusive.

- The only legal terminal events are `review_submitted` and `draft_expired`.
- A draft has at most one live creation event and at most one live terminal
  event.
- `review_opened` must not be earlier than creation; `review_submitted` must be strictly later.
- `draft_expired` must be more than 7 days after creation.
- Soft-deleting a row removes it from both partial unique indexes; a deleted
  draft can be recreated.

## Batch protocol

- 1..100 events per request.
- Surface validation (types, enums, required fields, batch conflicts) runs
  before any row is written; database-dependent rules run per event.
- Events are applied in type order (creation, opened, terminal) and then by
  `occurred_at`; caller order does not matter.
- Each event is written in a savepoint. A domain error rolls back the whole
  batch and returns 422/409, so partial batches are never committed.
- Same-batch duplicate event_ids with identical payloads are collapsed to one
  write plus one duplicate result. Different payloads are a 409.
- Already-stored event_ids are compared by payload; identical is a duplicate,
  different is a 409.

## Metric definitions

| Metric | Definition |
| --- | --- |
| Adoption rate | drafts with terminal action adopted_as_is or adopted_with_edits / all drafts with terminal review_submitted |
| As-is rate | adopted_as_is / review_submitted |
| Edited rate | adopted_with_edits / review_submitted |
| Rejection rate | rejected / review_submitted |
| Edit magnitude proxy | adopted_with_edits / (adopted_as_is + adopted_with_edits) |
| Review latency (wall) | review_submitted.occurred_at - ai_draft_created.occurred_at |
| Review latency (human) | sum(review_seconds) |
| Expiry rate | draft_expired / all terminal drafts |
| Reason mix | group by reject_reason_code where action = rejected |

## Error contract

All failures return `{"code": "...", "message": "..."}`:

- 422: malformed batch, invalid field, missing draft, invalid dictionary code,
  other without note, expiry at or before 7 days, duplicate creation.
- 409: duplicate terminal event, event_id reuse with a different payload.

## Compatibility

The spec is append-only at the event-type and field level. New optional fields
must be nullable and must not change existing semantics; new event types need a
new migration and a new terminal/state-machine rule. Removing or renaming a
field is a breaking change.
