"""Shared test doubles for sync tests."""

import io

from PIL import Image

from pixiv_archive.pixiv.models import BookmarkPage, UgoiraFrame, UgoiraMetadata
from pixiv_archive.pixiv.models import Illust as PixivIllust


def _jpeg_bytes(size: tuple[int, int] = (64, 48)) -> bytes:
    image = Image.new("RGB", size, color=(90, 120, 150))
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG")
    return buffer.getvalue()


_FAKE_IMAGE = _jpeg_bytes()


def make_illust(pid: int, *, type_: str = "illust", **overrides) -> PixivIllust:
    payload = {
        "id": pid,
        "title": f"t{pid}",
        "type": type_,
        "page_count": 1,
        "user": {"id": 1, "name": "artist", "account": "acct"},
        "tags": [{"name": "tag1", "translated_name": None}],
        "meta_single_page": {"original_image_url": f"https://i.pximg.net/{pid}.jpg"},
        "image_urls": {"square_medium": f"https://i.pximg.net/{pid}_sq.jpg"},
    }
    payload.update(overrides)
    return PixivIllust.model_validate(payload)


_STUB_URL = "https://s.pximg.net/common/images/limit_unknown_360.png"


def make_stub_illust(pid: int, **overrides) -> PixivIllust:
    """A bookmark entry for a deleted/private work, as pixiv returns it."""
    payload = {
        "id": pid,
        "title": "",
        "type": "illust",
        "page_count": 1,
        "user": {"id": 0, "name": "", "account": ""},
        "tags": [],
        "width": 100,
        "height": 100,
        "total_view": 0,
        "total_bookmarks": 0,
        "meta_single_page": {"original_image_url": _STUB_URL},
        "image_urls": {
            "square_medium": _STUB_URL,
            "medium": _STUB_URL,
            "large": _STUB_URL,
        },
    }
    payload.update(overrides)
    return PixivIllust.model_validate(payload)


def page(illusts: list[PixivIllust], cursor: int | None) -> BookmarkPage:
    next_url = (
        f"https://app-api.pixiv.net/v1/user/bookmarks/illust?user_id=1&max_bookmark_id={cursor}"
        if cursor is not None
        else None
    )
    return BookmarkPage(illusts=illusts, next_url=next_url)


class FakeClient:
    """Replays predefined bookmark pages and records requests."""

    def __init__(self, pages: dict[str, list[BookmarkPage]]) -> None:
        self.pages = {key: list(value) for key, value in pages.items()}
        self.page_requests: list[tuple[str, int | None]] = []
        self.ugoira_calls: list[int] = []
        self.ugoira_error: Exception | None = None
        self.ugoira_frames: list[dict[str, object]] = []

    async def list_bookmarks(self, restrict: str, *, max_bookmark_id: int | None = None):
        self.page_requests.append((restrict, max_bookmark_id))
        queue = self.pages.get(restrict, [])
        if not queue:
            return BookmarkPage(illusts=[], next_url=None)
        return queue.pop(0)

    async def get_ugoira_metadata(self, illust_id: int) -> UgoiraMetadata:
        self.ugoira_calls.append(illust_id)
        if self.ugoira_error is not None:
            raise self.ugoira_error
        return UgoiraMetadata(
            zip_url=f"https://i.pximg.net/{illust_id}.zip",
            frames=[UgoiraFrame.model_validate(f) for f in self.ugoira_frames],
        )


class FakeDownloader:
    """Writes fake image bytes; records requested urls.

    ``fetch_bytes`` returns a real (tiny) JPEG so image validation passes;
    ``fetch_to_file`` writes a real JPEG to the destination as well.
    """

    def __init__(self, fail_urls: set[str] | None = None) -> None:
        self.urls: list[str] = []
        self.fail_urls = fail_urls or set()

    async def fetch_to_file(self, url: str, dest) -> bool:
        self.urls.append(url)
        if url in self.fail_urls:
            return False
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(_FAKE_IMAGE)
        return True

    async def fetch_bytes(self, url: str) -> bytes | None:
        self.urls.append(url)
        if url in self.fail_urls:
            return None
        return _FAKE_IMAGE
