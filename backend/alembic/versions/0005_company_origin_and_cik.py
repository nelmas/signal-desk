"""company origin and SEC cik

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-11 18:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0005'
down_revision: str | None = '0004'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'companies',
        sa.Column('origin', sa.String(length=20), server_default='curated', nullable=False),
    )
    op.add_column('companies', sa.Column('cik', sa.String(length=10), nullable=True))
    op.create_index(op.f('ix_companies_cik'), 'companies', ['cik'], unique=False)
    op.create_check_constraint(
        op.f('ck_companies_origin'), 'companies', "origin IN ('curated', 'universe')"
    )


def downgrade() -> None:
    op.drop_constraint(op.f('ck_companies_origin'), 'companies', type_='check')
    op.drop_index(op.f('ix_companies_cik'), table_name='companies')
    op.drop_column('companies', 'cik')
    op.drop_column('companies', 'origin')
