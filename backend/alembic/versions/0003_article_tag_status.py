"""article tag status

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-11 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0003'
down_revision: str | None = '0002'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'articles',
        sa.Column('tag_status', sa.String(length=20), server_default='pending', nullable=False),
    )
    op.add_column(
        'articles',
        sa.Column('tag_attempts', sa.SmallInteger(), server_default='0', nullable=False),
    )
    op.create_index(op.f('ix_articles_tag_status'), 'articles', ['tag_status'], unique=False)
    op.create_check_constraint(
        op.f('ck_articles_tag_status'),
        'articles',
        "tag_status IN ('pending', 'no_match', 'tagged', 'irrelevant', 'failed')",
    )


def downgrade() -> None:
    op.drop_constraint(op.f('ck_articles_tag_status'), 'articles', type_='check')
    op.drop_index(op.f('ix_articles_tag_status'), table_name='articles')
    op.drop_column('articles', 'tag_attempts')
    op.drop_column('articles', 'tag_status')
