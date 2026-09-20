"""download tables

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-20

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "download_batch",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("scope", sa.String(32), nullable=False),
        sa.Column("filter_json", sa.Text(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="running"),
        sa.Column("cancelled", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("finished", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_table(
        "download_job",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("batch_id", sa.Integer(), sa.ForeignKey("download_batch.id"), nullable=True),
        sa.Column("pid", sa.BigInteger(), sa.ForeignKey("illust.pid"), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("target", sa.String(255), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("pid", "kind", "target", name="uq_download_job"),
    )
    op.create_index("ix_download_job_pid", "download_job", ["pid"])
    op.create_index("ix_download_job_status", "download_job", ["status"])
    op.create_index("ix_download_job_batch_id", "download_job", ["batch_id"])
    op.create_index("ix_download_job_status_batch", "download_job", ["status", "batch_id"])


def downgrade() -> None:
    op.drop_table("download_job")
    op.drop_table("download_batch")
