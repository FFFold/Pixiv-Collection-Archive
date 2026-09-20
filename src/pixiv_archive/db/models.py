from datetime import UTC, datetime

from sqlalchemy import BigInteger, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from pixiv_archive.db.base import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class Author(Base):
    __tablename__ = "author"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    name: Mapped[str] = mapped_column(String(255), default="")
    account: Mapped[str] = mapped_column(String(255), default="")
    avatar_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)


class Illust(Base):
    __tablename__ = "illust"

    pid: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    title: Mapped[str] = mapped_column(String(512), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    author_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("author.id"), index=True)
    create_date: Mapped[datetime | None] = mapped_column(nullable=True)
    page_count: Mapped[int] = mapped_column(default=1)
    width: Mapped[int] = mapped_column(default=0)
    height: Mapped[int] = mapped_column(default=0)
    type: Mapped[str] = mapped_column(String(16), default="illust")
    x_restrict: Mapped[int] = mapped_column(default=0)
    sanity_level: Mapped[int] = mapped_column(default=0)
    illust_ai_type: Mapped[int] = mapped_column(default=0)
    total_view: Mapped[int] = mapped_column(default=0)
    total_bookmarks: Mapped[int] = mapped_column(default=0)
    state: Mapped[str] = mapped_column(String(16), default="active")
    has_original: Mapped[bool] = mapped_column(default=False)
    page_downloaded_count: Mapped[int] = mapped_column(default=0)
    meta_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


class Bookmark(Base):
    __tablename__ = "bookmark"
    __table_args__ = (UniqueConstraint("pid", name="uq_bookmark_pid"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    pid: Mapped[int] = mapped_column(BigInteger, ForeignKey("illust.pid"), index=True)
    restrict: Mapped[str] = mapped_column(String(16), default="public")
    rank: Mapped[int] = mapped_column(BigInteger, index=True)
    state: Mapped[str] = mapped_column(String(16), default="active")
    first_seen_at: Mapped[datetime] = mapped_column(default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(default=utcnow)
    unbookmarked_at: Mapped[datetime | None] = mapped_column(nullable=True)


class AppSetting(Base):
    __tablename__ = "app_setting"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")


Index("ix_bookmark_state_rank", Bookmark.state, Bookmark.rank)
