from datetime import datetime
from urllib.parse import parse_qs, urlsplit

from pydantic import BaseModel, ConfigDict, Field


class PixivUser(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: int
    name: str = ""
    account: str = ""


class PixivTag(BaseModel):
    name: str = ""
    translated_name: str | None = None


class Illust(BaseModel):
    """Normalized view over a bookmark-list or detail illust object."""

    model_config = ConfigDict(populate_by_name=True)

    pid: int = Field(alias="id")
    title: str = ""
    description: str = ""
    type: str = "illust"
    page_count: int = 1
    width: int = 0
    height: int = 0
    x_restrict: int = 0
    sanity_level: int = 0
    illust_ai_type: int = 0
    total_view: int = 0
    total_bookmarks: int = 0
    create_date: datetime | None = None
    user: PixivUser
    tags: list[PixivTag] = Field(default_factory=list)
    meta_single_page: dict = Field(default_factory=dict)
    meta_pages: list[dict] = Field(default_factory=list)
    image_urls: dict = Field(default_factory=dict)

    @property
    def author(self) -> PixivUser:
        return self.user

    @property
    def original_urls(self) -> list[str]:
        urls: list[str] = []
        for page in self.meta_pages or []:
            url = (page.get("image_urls") or {}).get("original")
            if url:
                urls.append(url)
        if urls:
            return urls
        single = (self.meta_single_page or {}).get("original_image_url")
        return [single] if single else []

    @property
    def preview_url(self) -> str | None:
        return self.image_urls.get("square_medium") or self.image_urls.get("medium")


class BookmarkPage(BaseModel):
    illusts: list[Illust] = Field(default_factory=list)
    next_url: str | None = None

    @property
    def next_bookmark_id(self) -> int | None:
        """Extract max_bookmark_id from next_url; None when no cursor remains."""
        if not self.next_url:
            return None
        values = parse_qs(urlsplit(self.next_url).query).get("max_bookmark_id")
        if not values or not values[0]:
            return None
        try:
            return int(values[0])
        except ValueError:
            return None


class IllustDetail(BaseModel):
    illust: Illust


class UgoiraFrame(BaseModel):
    file: str
    delay: int


class UgoiraMetadata(BaseModel):
    zip_url: str | None = None
    frames: list[UgoiraFrame] = Field(default_factory=list)

    @classmethod
    def from_response(cls, payload: dict) -> "UgoiraMetadata":
        meta = payload.get("ugoira_metadata") or {}
        zip_urls = meta.get("zip_urls") or {}
        return cls(
            zip_url=zip_urls.get("original") or zip_urls.get("medium"),
            frames=[UgoiraFrame.model_validate(f) for f in meta.get("frames") or []],
        )
