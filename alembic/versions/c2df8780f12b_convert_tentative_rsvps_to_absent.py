"""convert tentative rsvps to absent

Revision ID: c2df8780f12b
Revises: 231f07ea87c4
Create Date: 2026-08-08 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c2df8780f12b'
down_revision: Union[str, Sequence[str], None] = '231f07ea87c4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

event_attendance = sa.table(
    "event_attendance",
    sa.column("status", sa.String),
)


def upgrade() -> None:
    """Fold existing 'tentative' RSVPs into 'absent' now that the option is gone."""
    op.execute(
        event_attendance.update()
        .where(event_attendance.c.status == "tentative")
        .values(status="absent")
    )


def downgrade() -> None:
    """No-op: original tentative/absent split can't be reconstructed."""
    pass
