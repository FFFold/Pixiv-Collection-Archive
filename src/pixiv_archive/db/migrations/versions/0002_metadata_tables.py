"""metadata tables

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-20

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tag",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(255), nullable=False, unique=True),
        sa.Column("translated_name", sa.String(255), nullable=True),
    )
    op.create_table(
        "illust_tag",
        sa.Column("pid", sa.BigInteger(), sa.ForeignKey("illust.pid"), primary_key=True),
        sa.Column("tag_id", sa.Integer(), sa.ForeignKey("tag.id"), primary_key=True),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_table(
        "illust_page",
        sa.Column("pid", sa.BigInteger(), sa.ForeignKey("illust.pid"), primary_key=True),
        sa.Column("page_index", sa.Integer(), primary_key=True),
        sa.Column("original_url", sa.String(1024), nullable=False),
        sa.Column("ext", sa.String(16), nullable=False, server_default=".jpg"),
        sa.Column("download_state", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
    )
    op.create_table(
        "ugoira_meta",
        sa.Column("pid", sa.BigInteger(), sa.ForeignKey("illust.pid"), primary_key=True),
        sa.Column("zip_url", sa.String(1024), nullable=False, server_default=""),
        sa.Column("frames_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("frame_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_table(
        "sync_run",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="running"),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("pages_fetched", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("new_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("unbookmarked_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rank_rebuilt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("previews_fetched", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("previews_failed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("sync_run")
    op.drop_table("ugoira_meta")
    op.drop_table("illust_page")
    op.drop_table("illust_tag")
    op.drop_table("tag")
