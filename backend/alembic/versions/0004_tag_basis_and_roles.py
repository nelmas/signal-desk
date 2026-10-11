"""tag basis and per-company roles; re-tag v1 articles

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-11 15:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0004'
down_revision: str | None = '0003'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'article_analyses',
        sa.Column('basis', sa.String(length=20), server_default='reported', nullable=False),
    )
    op.create_check_constraint(
        op.f('ck_article_analyses_basis'),
        'article_analyses',
        "basis IN ('announced', 'reported', 'commentary')",
    )
    op.add_column(
        'article_companies',
        sa.Column('role', sa.String(length=20), server_default='subject', nullable=False),
    )
    op.add_column(
        'article_companies', sa.Column('sentiment', sa.Numeric(precision=4, scale=3), nullable=True)
    )
    op.create_check_constraint(
        op.f('ck_article_companies_role'), 'article_companies', "role IN ('subject', 'affected')"
    )
    op.create_check_constraint(
        op.f('ck_article_companies_sentiment_range'),
        'article_companies',
        'sentiment BETWEEN -1 AND 1',
    )

    # Tags from prompt tag-v1 lack basis and per-company roles: send them back to the AI.
    op.execute(
        """
        UPDATE articles SET tag_status = 'pending', tag_attempts = 0
        WHERE id IN (SELECT article_id FROM article_analyses WHERE prompt_version = 'tag-v1')
        """
    )
    op.execute(
        """
        DELETE FROM article_companies WHERE article_id IN
          (SELECT article_id FROM article_analyses WHERE prompt_version = 'tag-v1')
        """
    )
    op.execute("DELETE FROM article_analyses WHERE prompt_version = 'tag-v1'")


def downgrade() -> None:
    op.drop_constraint(
        op.f('ck_article_companies_sentiment_range'), 'article_companies', type_='check'
    )
    op.drop_constraint(op.f('ck_article_companies_role'), 'article_companies', type_='check')
    op.drop_column('article_companies', 'sentiment')
    op.drop_column('article_companies', 'role')
    op.drop_constraint(op.f('ck_article_analyses_basis'), 'article_analyses', type_='check')
    op.drop_column('article_analyses', 'basis')
