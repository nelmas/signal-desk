"""benchmark prices

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-15 18:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0007'
down_revision: str | None = '0006'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'benchmark_prices',
        sa.Column('symbol', sa.String(length=30), nullable=False),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('open', sa.Numeric(precision=18, scale=6), nullable=True),
        sa.Column('close', sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column('source', sa.String(length=50), nullable=False),
        sa.PrimaryKeyConstraint('symbol', 'date', name=op.f('pk_benchmark_prices')),
    )


def downgrade() -> None:
    op.drop_table('benchmark_prices')
