"""preview and ugoira metadata state

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-19

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "illust",
        sa.Column("preview_state", sa.String(16), nullable=False, server_default="pending"),
    )
    op.add_column(
        "illust",
        sa.Column("preview_attempts", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("illust", sa.Column("preview_error", sa.Text(), nullable=True))
    op.add_column(
        "ugoira_meta",
        sa.Column("meta_attempts", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("ugoira_meta", sa.Column("meta_error", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("ugoira_meta", "meta_error")
    op.drop_column("ugoira_meta", "meta_attempts")
    op.drop_column("illust", "preview_error")
    op.drop_column("illust", "preview_attempts")
    op.drop_column("illust", "preview_state")
