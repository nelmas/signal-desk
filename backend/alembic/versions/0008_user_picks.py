"""your own picks in the track record

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-20 20:00:00.000000

Ideas get an origin: "agent" (from a briefing) or "user" (picked on a stock page).
The web role may add picks and remove them before they enter (enforced in the app).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0008'
down_revision: str | None = '0007'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ROLE = "signal_desk_web"


def _if_role(sql: str) -> None:
    op.execute(
        f"DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{ROLE}') "
        f"THEN {sql} END IF; END $$"
    )


def upgrade() -> None:
    op.add_column(
        'ideas', sa.Column('origin', sa.String(length=10), server_default='agent', nullable=False)
    )
    op.alter_column('ideas', 'briefing_id', existing_type=sa.Integer(), nullable=True)
    op.alter_column('ideas', 'confidence', existing_type=sa.String(length=10), nullable=True)
    op.alter_column('ideas', 'risks', existing_type=sa.Text(), server_default='')
    op.create_check_constraint(op.f('ck_ideas_origin'), 'ideas', "origin IN ('agent', 'user')")
    op.create_check_constraint(
        op.f('ck_ideas_agent_has_briefing'), 'ideas', "origin = 'user' OR briefing_id IS NOT NULL"
    )
    _if_role(f"GRANT INSERT, DELETE ON ideas TO {ROLE};")
    _if_role(f"GRANT USAGE ON SEQUENCE ideas_id_seq TO {ROLE};")


def downgrade() -> None:
    _if_role(f"REVOKE USAGE ON SEQUENCE ideas_id_seq FROM {ROLE};")
    _if_role(f"REVOKE INSERT, DELETE ON ideas FROM {ROLE};")
    op.drop_constraint(op.f('ck_ideas_agent_has_briefing'), 'ideas', type_='check')
    op.drop_constraint(op.f('ck_ideas_origin'), 'ideas', type_='check')
    op.execute("DELETE FROM ideas WHERE origin = 'user'")
    op.alter_column('ideas', 'risks', existing_type=sa.Text(), server_default=None)
    op.alter_column('ideas', 'confidence', existing_type=sa.String(length=10), nullable=False)
    op.alter_column('ideas', 'briefing_id', existing_type=sa.Integer(), nullable=False)
    op.drop_column('ideas', 'origin')
