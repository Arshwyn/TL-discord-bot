"""split need/alt-want loot decay, remove greed decay

Revision ID: f2b55cd91877
Revises: c2df8780f12b
Create Date: 2026-09-26 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f2b55cd91877'
down_revision: Union[str, Sequence[str], None] = 'c2df8780f12b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('user_profiles') as batch_op:
        batch_op.alter_column('loot_wins', new_column_name='need_wins')
        batch_op.add_column(sa.Column('alt_want_wins', sa.Integer(), server_default='0', nullable=False))

    op.add_column('loot_items', sa.Column('winner_roll_type', sa.String(length=20), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('loot_items', 'winner_roll_type')

    with op.batch_alter_table('user_profiles') as batch_op:
        batch_op.drop_column('alt_want_wins')
        batch_op.alter_column('need_wins', new_column_name='loot_wins')
