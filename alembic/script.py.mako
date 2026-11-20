"""${message}"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
${imports if imports else ""}


revision: str = ${up_revision}
down_revision: str | None = ${down_revision}
branch_labels: str | Sequence[str] | None = ${branch_labels}
depends_on: str | Sequence[str] | None = ${depends_on}


def upgrade() -> None:
    ${upgrades}


def downgrade() -> None:
    ${downgrades}
