"""drop loot_items.announcement_message_id (main card is a single message again)

Revision ID: a3547e585507
Revises: a451f2df14a8
Create Date: 2026-07-10 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a3547e585507'
down_revision: Union[str, Sequence[str], None] = 'a451f2df14a8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('loot_items') as batch_op:
        batch_op.drop_column('announcement_message_id')


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('loot_items') as batch_op:
        batch_op.add_column(sa.Column('announcement_message_id', sa.BigInteger(), nullable=True))
