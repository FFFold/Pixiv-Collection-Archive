"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-09-20

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "author",
        sa.Column("id", sa.BigInteger(), autoincrement=False, primary_key=True),
        sa.Column("name", sa.String(255), nullable=False, server_default=""),
        sa.Column("account", sa.String(255), nullable=False, server_default=""),
        sa.Column("avatar_url", sa.String(1024), nullable=True),
    )
    op.create_table(
        "illust",
        sa.Column("pid", sa.BigInteger(), autoincrement=False, primary_key=True),
        sa.Column("title", sa.String(512), nullable=False, server_default=""),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("author_id", sa.BigInteger(), sa.ForeignKey("author.id"), nullable=False),
        sa.Column("create_date", sa.DateTime(), nullable=True),
        sa.Column("page_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("width", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("height", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("type", sa.String(16), nullable=False, server_default="illust"),
        sa.Column("x_restrict", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sanity_level", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("illust_ai_type", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_view", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_bookmarks", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("state", sa.String(16), nullable=False, server_default="active"),
        sa.Column("has_original", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("page_downloaded_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("meta_json", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_illust_author_id", "illust", ["author_id"])
    op.create_table(
        "bookmark",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("pid", sa.BigInteger(), sa.ForeignKey("illust.pid"), nullable=False),
        sa.Column("restrict", sa.String(16), nullable=False, server_default="public"),
        sa.Column("rank", sa.BigInteger(), nullable=False),
        sa.Column("state", sa.String(16), nullable=False, server_default="active"),
        sa.Column("first_seen_at", sa.DateTime(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False),
        sa.Column("unbookmarked_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("pid", name="uq_bookmark_pid"),
    )
    op.create_index("ix_bookmark_pid", "bookmark", ["pid"])
    op.create_index("ix_bookmark_rank", "bookmark", ["rank"])
    op.create_index("ix_bookmark_state_rank", "bookmark", ["state", "rank"])
    op.create_table(
        "app_setting",
        sa.Column("key", sa.String(128), primary_key=True),
        sa.Column("value", sa.Text(), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_table("app_setting")
    op.drop_table("bookmark")
    op.drop_table("illust")
    op.drop_table("author")
