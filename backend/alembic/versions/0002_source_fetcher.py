"""source fetcher

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-04 19:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0002'
down_revision: str | None = '0001'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'sources', sa.Column('fetcher', sa.String(length=50), server_default='rss', nullable=False)
    )


def downgrade() -> None:
    op.drop_column('sources', 'fetcher')
