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
    byte_size: Mapped[int] = mapped_column(BigInteger, default=0)
    thumb_ready: Mapped[bool] = mapped_column(default=False)
    animation_ready: Mapped[bool] = mapped_column(default=False)
    meta_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)

    @property
    def is_unavailable(self) -> bool:
        """True when pixiv no longer serves this work (deleted or private)."""
        return self.state == "deleted"


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


class Tag(Base):
    __tablename__ = "tag"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), unique=True)
    translated_name: Mapped[str | None] = mapped_column(String(255), nullable=True)


class IllustTag(Base):
    __tablename__ = "illust_tag"

    pid: Mapped[int] = mapped_column(BigInteger, ForeignKey("illust.pid"), primary_key=True)
    tag_id: Mapped[int] = mapped_column(ForeignKey("tag.id"), primary_key=True)
    position: Mapped[int] = mapped_column(default=0)


class IllustPage(Base):
    __tablename__ = "illust_page"

    pid: Mapped[int] = mapped_column(BigInteger, ForeignKey("illust.pid"), primary_key=True)
    page_index: Mapped[int] = mapped_column(primary_key=True)
    original_url: Mapped[str] = mapped_column(String(1024))
    ext: Mapped[str] = mapped_column(String(16), default=".jpg")
    download_state: Mapped[str] = mapped_column(String(16), default="pending")
    attempts: Mapped[int] = mapped_column(default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class UgoiraMeta(Base):
    __tablename__ = "ugoira_meta"

    pid: Mapped[int] = mapped_column(BigInteger, ForeignKey("illust.pid"), primary_key=True)
    zip_url: Mapped[str] = mapped_column(String(1024), default="")
    frames_json: Mapped[str] = mapped_column(Text, default="[]")
    frame_count: Mapped[int] = mapped_column(default=0)


class SyncRun(Base):
    __tablename__ = "sync_run"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), default="running")
    started_at: Mapped[datetime] = mapped_column(default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(nullable=True)
    pages_fetched: Mapped[int] = mapped_column(default=0)
    new_count: Mapped[int] = mapped_column(default=0)
    unbookmarked_count: Mapped[int] = mapped_column(default=0)
    rank_rebuilt_count: Mapped[int] = mapped_column(default=0)
    previews_fetched: Mapped[int] = mapped_column(default=0)
    previews_failed: Mapped[int] = mapped_column(default=0)
    failed_count: Mapped[int] = mapped_column(default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class DownloadBatch(Base):
    __tablename__ = "download_batch"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    scope: Mapped[str] = mapped_column(String(32))
    filter_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="running")
    cancelled: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(nullable=True)
    total: Mapped[int] = mapped_column(default=0)
    finished: Mapped[int] = mapped_column(default=0)
    failed: Mapped[int] = mapped_column(default=0)


class DownloadJob(Base):
    __tablename__ = "download_job"
    __table_args__ = (UniqueConstraint("pid", "kind", "target", name="uq_download_job"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    batch_id: Mapped[int | None] = mapped_column(
        ForeignKey("download_batch.id"), nullable=True, index=True
    )
    pid: Mapped[int] = mapped_column(BigInteger, ForeignKey("illust.pid"), index=True)
    kind: Mapped[str] = mapped_column(String(16))
    target: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    attempts: Mapped[int] = mapped_column(default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


Index("ix_download_job_status_batch", DownloadJob.status, DownloadJob.batch_id)


Index("ix_bookmark_state_rank", Bookmark.state, Bookmark.rank)
