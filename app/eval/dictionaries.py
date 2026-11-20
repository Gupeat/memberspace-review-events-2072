"""Reject-reason dictionary and deterministic seed rows."""
from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.eval.constants import GLOBAL_ORG_ID
from app.eval.models import AiRejectReason

GLOBAL_ORG = uuid.UUID(GLOBAL_ORG_ID)


@dataclass(frozen=True)
class ReasonSeed:
    id: uuid.UUID
    code: str
    label_zh: str
    label_en: str
    requires_note: bool
    sort_order: int


SEEDS = (
    ReasonSeed(uuid.UUID(int=7001001), "factual_error", "事实错误", "Factual error", False, 10),
    ReasonSeed(uuid.UUID(int=7001002), "off_tone", "语气不符", "Off tone", False, 20),
    ReasonSeed(uuid.UUID(int=7001003), "missing_info", "信息缺失", "Missing information", False, 30),
    ReasonSeed(uuid.UUID(int=7001004), "policy_violation", "违反规范", "Policy violation", False, 40),
    ReasonSeed(uuid.UUID(int=7001005), "duplicate", "重复", "Duplicate", False, 50),
    ReasonSeed(uuid.UUID(int=7001006), "not_needed", "不需要", "Not needed", False, 60),
    ReasonSeed(uuid.UUID(int=7001007), "other", "其他", "Other", True, 70),
)


def seed_reject_reasons(session: Session) -> int:
    """Insert missing global rows; safe to call repeatedly. Returns inserted count."""
    existing = set(
        session.scalars(
            select(AiRejectReason.code).where(AiRejectReason.org_id == GLOBAL_ORG)
        ).all()
    )
    inserted = 0
    for seed in SEEDS:
        if seed.code in existing:
            continue
        session.add(
            AiRejectReason(
                id=seed.id,
                org_id=GLOBAL_ORG,
                code=seed.code,
                label_zh=seed.label_zh,
                label_en=seed.label_en,
                requires_note=seed.requires_note,
                sort_order=seed.sort_order,
                active=True,
            )
        )
        inserted += 1
    session.commit()
    return inserted


def get_reason(session: Session, code: str) -> AiRejectReason | None:
    return session.scalar(
        select(AiRejectReason).where(
            AiRejectReason.org_id == GLOBAL_ORG,
            AiRejectReason.code == code,
            AiRejectReason.active.is_(True),
        )
    )


def list_reasons(session: Session) -> list[AiRejectReason]:
    return list(
        session.scalars(
            select(AiRejectReason)
            .where(AiRejectReason.org_id == GLOBAL_ORG)
            .order_by(AiRejectReason.sort_order, AiRejectReason.code)
        ).all()
    )
