"""loot threads and no-penalty solo greed

Revision ID: a451f2df14a8
Revises: e199f62d1f22
Create Date: 2026-07-10 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a451f2df14a8'
down_revision: Union[str, Sequence[str], None] = 'e199f62d1f22'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('loot_items', sa.Column('announcement_message_id', sa.BigInteger(), nullable=True))
    op.add_column('loot_items', sa.Column('thread_id', sa.BigInteger(), nullable=True))
    op.add_column('loot_items', sa.Column('closed_at', sa.DateTime(), nullable=True))
    op.add_column('loot_items', sa.Column('winner_penalized', sa.Boolean(), server_default=sa.false(), nullable=False))
    op.add_column('loot_items', sa.Column('is_archived', sa.Boolean(), server_default=sa.false(), nullable=False))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('loot_items', 'is_archived')
    op.drop_column('loot_items', 'winner_penalized')
    op.drop_column('loot_items', 'closed_at')
    op.drop_column('loot_items', 'thread_id')
    op.drop_column('loot_items', 'announcement_message_id')
