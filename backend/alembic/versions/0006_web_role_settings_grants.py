"""web role may edit settings and the watchlist

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-15 14:00:00.000000

The web app's database role (signal_desk_web) is read-only except for the two tables
the Settings page edits. Skipped when the role doesn't exist (tests, fresh setups).
"""

from collections.abc import Sequence

from alembic import op

revision: str = '0006'
down_revision: str | None = '0005'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ROLE = "signal_desk_web"


def _if_role(sql: str) -> None:
    op.execute(
        f"DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{ROLE}') "
        f"THEN {sql} END IF; END $$"
    )


def upgrade() -> None:
    _if_role(f"GRANT INSERT, UPDATE ON settings TO {ROLE};")
    _if_role(f"GRANT INSERT, UPDATE, DELETE ON tracked_stocks TO {ROLE};")


def downgrade() -> None:
    _if_role(f"REVOKE INSERT, UPDATE ON settings FROM {ROLE};")
    _if_role(f"REVOKE INSERT, UPDATE, DELETE ON tracked_stocks FROM {ROLE};")
