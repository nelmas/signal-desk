"""the Radar: rule-based early signals, tracked in Facit

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-21 09:00:00.000000

Ideas may now come from the Radar ("radar"), with the signal that fired and its evidence.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0009'
down_revision: str | None = '0008'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('ideas', sa.Column('signal', sa.String(length=30), nullable=True))
    op.add_column(
        'ideas',
        sa.Column('details', postgresql.JSONB(), server_default='{}', nullable=False),
    )
    op.drop_constraint(op.f('ck_ideas_agent_has_briefing'), 'ideas', type_='check')
    op.drop_constraint(op.f('ck_ideas_origin'), 'ideas', type_='check')
    op.create_check_constraint(
        op.f('ck_ideas_origin'), 'ideas', "origin IN ('agent', 'radar', 'user')"
    )
    op.create_check_constraint(
        op.f('ck_ideas_agent_has_briefing'), 'ideas', "origin <> 'agent' OR briefing_id IS NOT NULL"
    )
    op.create_check_constraint(
        op.f('ck_ideas_radar_has_signal'), 'ideas', "(origin = 'radar') = (signal IS NOT NULL)"
    )
    op.create_index('ix_ideas_radar', 'ideas', ['company_id', 'signal', 'published_at'])


def downgrade() -> None:
    op.drop_index('ix_ideas_radar', table_name='ideas')
    op.execute("DELETE FROM ideas WHERE origin = 'radar'")
    op.drop_constraint(op.f('ck_ideas_radar_has_signal'), 'ideas', type_='check')
    op.drop_constraint(op.f('ck_ideas_agent_has_briefing'), 'ideas', type_='check')
    op.drop_constraint(op.f('ck_ideas_origin'), 'ideas', type_='check')
    op.create_check_constraint(op.f('ck_ideas_origin'), 'ideas', "origin IN ('agent', 'user')")
    op.create_check_constraint(
        op.f('ck_ideas_agent_has_briefing'), 'ideas', "origin = 'user' OR briefing_id IS NOT NULL"
    )
    op.drop_column('ideas', 'details')
    op.drop_column('ideas', 'signal')
