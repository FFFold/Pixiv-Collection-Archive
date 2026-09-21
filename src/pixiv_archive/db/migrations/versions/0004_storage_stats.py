"""storage stats columns

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-21

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "illust", sa.Column("byte_size", sa.BigInteger(), nullable=False, server_default="0")
    )
    op.add_column(
        "illust", sa.Column("thumb_ready", sa.Boolean(), nullable=False, server_default="0")
    )
    op.add_column(
        "illust", sa.Column("animation_ready", sa.Boolean(), nullable=False, server_default="0")
    )


def downgrade() -> None:
    op.drop_column("illust", "animation_ready")
    op.drop_column("illust", "thumb_ready")
    op.drop_column("illust", "byte_size")
