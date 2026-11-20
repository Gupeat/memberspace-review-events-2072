from __future__ import annotations

import uuid

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from app.eval.models import AiReviewEvent
from app.main import create_app
from tests.factories import ORG_A
from tests.test_service import api_event
from tests.factories import draft_row, expired_row, opened_row, submitted_row


def make_client(engine):
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    return TestClient(create_app(factory)), factory


def count_rows(factory):
    with factory() as session:
        return session.scalar(select(func.count()).select_from(AiReviewEvent))


def test_healthz(engine):
    client, _ = make_client(engine)
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ac1_101_events_return_422(engine):
    client, factory = make_client(engine)
    events = [
        api_event(draft_row(id=uuid.uuid4(), draft_id=uuid.uuid4())) for _ in range(101)
    ]
    response = client.post("/api/eval/review-events", json={"events": events})
    assert response.status_code == 422
    assert response.json() == {
        "code": "BATCH_TOO_LARGE",
        "message": "a batch may contain at most 100 events",
    }
    assert count_rows(factory) == 0


def test_ac1_100_events_return_200_and_are_written(engine):
    client, factory = make_client(engine)
    events = [
        api_event(draft_row(id=uuid.uuid4(), draft_id=uuid.uuid4())) for _ in range(100)
    ]
    response = client.post(
        "/api/eval/review-events",
        json={"events": events},
        headers={"X-Org-Id": str(ORG_A)},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["created"] == 100
    assert body["duplicates"] == 0
    assert body["received"] == 100
    assert len(body["items"]) == 100
    assert count_rows(factory) == 100


def test_bare_array_body_is_accepted(engine):
    client, factory = make_client(engine)
    response = client.post("/api/eval/review-events", json=[api_event(draft_row())])
    assert response.status_code == 200
    assert response.json()["created"] == 1
    assert count_rows(factory) == 1


def test_ac2_duplicate_event_is_idempotent(engine):
    client, factory = make_client(engine)
    event = api_event(draft_row())
    first = client.post("/api/eval/review-events", json={"events": [event]})
    second = client.post("/api/eval/review-events", json={"events": [event]})
    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["created"] == 0
    assert second.json()["duplicates"] == 1
    assert count_rows(factory) == 1


def test_ac3_second_terminal_returns_409(engine):
    client, factory = make_client(engine)
    client.post("/api/eval/review-events", json={"events": [api_event(draft_row())]})
    client.post("/api/eval/review-events", json={"events": [api_event(submitted_row())]})
    response = client.post("/api/eval/review-events", json={"events": [api_event(expired_row())]})
    assert response.status_code == 409
    assert response.json()["code"] == "DRAFT_ALREADY_TERMINAL"
    assert count_rows(factory) == 2


def test_ac4_other_without_note_returns_422(engine):
    client, factory = make_client(engine)
    row = submitted_row("rejected")
    row["reject_reason_code"] = "other"
    row.pop("reject_reason_note", None)
    response = client.post(
        "/api/eval/review-events",
        json={"events": [api_event(draft_row()), api_event(row)]},
    )
    assert response.status_code == 422
    assert response.json()["code"] == "OTHER_NOTE_REQUIRED"
    assert count_rows(factory) == 0


def test_review_before_creation_returns_422(engine):
    client, factory = make_client(engine)
    response = client.post("/api/eval/review-events", json={"events": [api_event(opened_row())]})
    assert response.status_code == 422
    assert response.json()["code"] == "DRAFT_NOT_FOUND"
    assert count_rows(factory) == 0


def test_batch_order_is_irrelevant_over_http(engine):
    client, factory = make_client(engine)
    response = client.post(
        "/api/eval/review-events",
        json={"events": [api_event(submitted_row()), api_event(opened_row()), api_event(draft_row())]},
    )
    assert response.status_code == 200
    assert response.json()["created"] == 3
    assert count_rows(factory) == 3


def test_unknown_field_is_rejected(engine):
    client, factory = make_client(engine)
    event = api_event(draft_row())
    event["unexpected"] = "x"
    response = client.post("/api/eval/review-events", json={"events": [event]})
    assert response.status_code == 422
    assert response.json()["code"] == "EVENT_FIELD_INVALID"
    assert count_rows(factory) == 0


def test_invalid_json_returns_422(engine):
    client, _ = make_client(engine)
    response = client.post(
        "/api/eval/review-events",
        content="{not json",
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 422
    assert response.json()["code"] == "REQUEST_INVALID"


def test_missing_events_key_returns_422(engine):
    client, _ = make_client(engine)
    response = client.post("/api/eval/review-events", json={"items": []})
    assert response.status_code == 422
    assert response.json()["code"] == "EVENT_FIELD_INVALID"


def test_invalid_org_header_returns_422(engine):
    client, _ = make_client(engine)
    response = client.post(
        "/api/eval/review-events",
        json={"events": [api_event(draft_row())]},
        headers={"X-Org-Id": "not-a-uuid"},
    )
    assert response.status_code == 422
    assert response.json()["code"] == "ORG_INVALID"
