from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    token: str


class MeResponse(BaseModel):
    authenticated: bool


class GalleryItem(BaseModel):
    pid: int
    index: int
    title: str
    author_id: int
    author_name: str
    page_count: int
    type: str
    x_restrict: int
    width: int
    height: int
    create_date: datetime | None
    rank: int
    has_original: bool
    page_downloaded_count: int
    preview_url: str
    thumb_url: str
    restrict: str
    unbookmarked: bool
    state: str


class GalleryResponse(BaseModel):
    items: list[GalleryItem]
    total: int
    offset: int
    limit: int


class IllustPageOut(BaseModel):
    page_index: int
    download_state: str
    ext: str
    width: int | None = None
    height: int | None = None


class IllustDetailOut(BaseModel):
    pid: int
    index: int
    title: str
    description: str
    author_id: int
    author_name: str
    author_account: str
    page_count: int
    type: str
    x_restrict: int
    sanity_level: int
    width: int
    height: int
    create_date: datetime | None
    total_view: int
    total_bookmarks: int
    state: str
    has_original: bool
    page_downloaded_count: int
    tags: list[str]
    translated_tags: list[str]
    pages: list[IllustPageOut]
    restrict: str
    bookmark_state: str
    rank: int | None
    pixiv_url: str
    animation_available: bool
    frame_count: int | None
    unbookmarked: bool


class AuthorOut(BaseModel):
    id: int
    name: str
    account: str
    illust_count: int


class TagOut(BaseModel):
    name: str
    translated_name: str | None
    illust_count: int


class SyncRequest(BaseModel):
    mode: str = "incremental"


class DownloadRequest(BaseModel):
    scope: str = "all_missing"
    pids: list[int] = Field(default_factory=list)
    author_id: int | None = None
    start: int | None = None
    count: int | None = None
    x_restrict: int | None = None
    type: str | None = None
    with_thumbs: bool = True
    # filter-scope extras (same fields as the gallery filters)
    tags: list[str] = Field(default_factory=list)
    author_ids: list[int] = Field(default_factory=list)
    q: str | None = None
    restrict: str | None = None
    downloaded: bool | None = None
    page_min: int | None = None
    page_max: int | None = None
    bookmarks_min: int | None = None
    bookmarks_max: int | None = None
    views_min: int | None = None
    views_max: int | None = None
    only_unbookmarked: bool = False
    include_unbookmarked: bool = False


class TaskOut(BaseModel):
    id: str
    kind: str
    status: str
    started_at: datetime
    finished_at: datetime | None = None
    detail: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class StatsOut(BaseModel):
    total_illusts: int
    unbookmarked: int
    total_pages: int
    downloaded_pages: int
    failed_pages: int
    pending_pages: int
    total_bytes: int
    thumbs_ready: int
    ugoira_count: int
    animation_ready: int
    by_type: dict[str, int]
    by_restrict: dict[str, int]


class ExportRequest(BaseModel):
    include_metadata: bool = True
    include_originals: bool = False
    pids: list[int] = Field(default_factory=list)
    x_restrict: int | None = None
    only_downloaded: bool = False


class ExportOut(BaseModel):
    task_id: str
    filename: str


class EventOut(BaseModel):
    type: str
    payload: dict[str, Any]
