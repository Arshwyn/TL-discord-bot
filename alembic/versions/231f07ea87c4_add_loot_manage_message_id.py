"""add loot_items.manage_message_id (thread control-panel message)

Revision ID: 231f07ea87c4
Revises: a3547e585507
Create Date: 2026-07-10 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '231f07ea87c4'
down_revision: Union[str, Sequence[str], None] = 'a3547e585507'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('loot_items', sa.Column('manage_message_id', sa.BigInteger(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('loot_items', 'manage_message_id')
