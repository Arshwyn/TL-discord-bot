"""split need/alt-want loot decay into its own per-user table, remove greed decay

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
    # Loot decay is a per-Discord-user concept, but user_profiles is keyed by (discord_id,
    # build_name) — a member with multiple builds had their old shared loot_wins counter
    # scattered across arbitrary rows. Give decay its own table keyed by discord_id alone.
    op.create_table(
        'loot_priority',
        sa.Column('discord_id', sa.BigInteger(), primary_key=True),
        sa.Column('need_wins', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('alt_want_wins', sa.Integer(), nullable=False, server_default='0'),
    )

    # Carry forward existing penalties: collapse however many build rows a user has down to one
    # by taking the max. Every value >=2 already meant "0% priority", so this can't under-count
    # anyone relative to how the old shared counter behaved.
    op.execute("""
        INSERT INTO loot_priority (discord_id, need_wins, alt_want_wins)
        SELECT discord_id, MAX(loot_wins), 0
        FROM user_profiles
        GROUP BY discord_id
    """)

    with op.batch_alter_table('user_profiles') as batch_op:
        batch_op.drop_column('loot_wins')

    op.add_column('loot_items', sa.Column('winner_roll_type', sa.String(length=20), nullable=True))

    # Backfill winner_roll_type for items closed before this deploy. The winning roll entry is
    # still sitting in loot_rolls for any item that hasn't been rerolled yet, so recover the
    # category from there. An item already rerolled with no matching entry left NULL is no worse
    # off than before this migration — its refund was never resolvable either way.
    op.execute("""
        UPDATE loot_items
        SET winner_roll_type = (
            SELECT roll_type FROM loot_rolls
            WHERE loot_rolls.loot_item_id = loot_items.id
              AND loot_rolls.discord_id = loot_items.winner_id
        )
        WHERE winner_penalized = 1
          AND winner_id IS NOT NULL
          AND winner_roll_type IS NULL
    """)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('loot_items', 'winner_roll_type')

    with op.batch_alter_table('user_profiles') as batch_op:
        batch_op.add_column(sa.Column('loot_wins', sa.Integer(), server_default='0', nullable=False))

    op.execute("""
        UPDATE user_profiles
        SET loot_wins = (
            SELECT need_wins FROM loot_priority
            WHERE loot_priority.discord_id = user_profiles.discord_id
        )
        WHERE EXISTS (
            SELECT 1 FROM loot_priority WHERE loot_priority.discord_id = user_profiles.discord_id
        )
    """)

    op.drop_table('loot_priority')
