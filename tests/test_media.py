import httpx

from pixiv_archive.media.downloader import ImageDownloader, apply_image_mirror
from pixiv_archive.media.storage import WorksStorage, atomic_write_bytes


def test_apply_image_mirror_replaces_official_hosts():
    mirror = "mirror.example.com"
    assert (
        apply_image_mirror("https://i.pximg.net/img/a.jpg?x=1", mirror)
        == "https://mirror.example.com/img/a.jpg?x=1"
    )
    assert (
        apply_image_mirror("https://s.pximg.net/av/b.png", mirror)
        == "https://mirror.example.com/av/b.png"
    )


def test_apply_image_mirror_ignores_other_hosts_and_empty_mirror():
    url = "https://example.com/a.jpg"
    assert apply_image_mirror(url, "mirror.example.com") == url
    assert apply_image_mirror("https://i.pximg.net/a.jpg", None) == "https://i.pximg.net/a.jpg"


def test_apply_image_mirror_accepts_scheme_and_strips_slashes():
    assert (
        apply_image_mirror("https://i.pximg.net/a.jpg", "https://mirror.example.com/")
        == "https://mirror.example.com/a.jpg"
    )


def test_apply_image_mirror_rejects_invalid_mirror():
    url = "https://i.pximg.net/a.jpg"
    assert apply_image_mirror(url, "bad mirror with spaces") == url


def test_storage_layout(tmp_path):
    storage = WorksStorage(tmp_path)
    assert storage.work_dir(123) == tmp_path / "123"
    assert storage.preview_path(123) == tmp_path / "123" / "preview.jpg"
    assert storage.thumb_path(123) == tmp_path / "123" / "thumb.webp"
    assert storage.original_dir(123) == tmp_path / "123" / "original"
    assert storage.meta_path(123) == tmp_path / "123" / "meta.json"
    assert storage.animation_path(123) == tmp_path / "123" / "animation.mp4"


def test_atomic_write_bytes(tmp_path):
    dest = tmp_path / "sub" / "file.bin"
    atomic_write_bytes(dest, b"payload")
    assert dest.read_bytes() == b"payload"
    assert not (tmp_path / "sub" / "file.bin.part").exists()


def test_storage_save_meta_json_and_preview(tmp_path):
    storage = WorksStorage(tmp_path)
    storage.save_meta_json(42, {"id": 42, "title": "t"})
    assert storage.meta_path(42).exists()
    assert storage.has_preview(42) is False
    storage.save_preview(42, b"jpegbytes")
    assert storage.has_preview(42) is True
    assert storage.preview_path(42).read_bytes() == b"jpegbytes"


def _image_client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_downloader_fetch_to_file(tmp_path):
    seen_headers = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen_headers.update(request.headers)
        return httpx.Response(200, content=b"img-bytes")

    downloader = ImageDownloader(_image_client(handler), mirror=None, concurrency=2)
    dest = tmp_path / "x.jpg"
    assert await downloader.fetch_to_file("https://i.pximg.net/x.jpg", dest) is True
    assert dest.read_bytes() == b"img-bytes"
    assert seen_headers["referer"] == "https://www.pixiv.net/"


async def test_downloader_returns_false_on_404(tmp_path):
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(404)

    downloader = ImageDownloader(_image_client(handler), mirror=None, concurrency=1)
    assert (
        await downloader.fetch_to_file("https://i.pximg.net/gone.jpg", tmp_path / "g.jpg") is False
    )
    assert calls["n"] == 1  # 404 must not be retried
    assert not (tmp_path / "g.jpg").exists()


async def test_downloader_retries_transient_errors(tmp_path):
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(500)
        return httpx.Response(200, content=b"ok")

    downloader = ImageDownloader(_image_client(handler), mirror=None, concurrency=1)
    assert await downloader.fetch_to_file("https://i.pximg.net/r.jpg", tmp_path / "r.jpg") is True
    assert calls["n"] == 3


async def test_downloader_mirror_falls_back_to_official(tmp_path):
    hosts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        hosts.append(request.url.host)
        if request.url.host == "mirror.example.com":
            return httpx.Response(403)
        return httpx.Response(200, content=b"official")

    downloader = ImageDownloader(_image_client(handler), mirror="mirror.example.com", concurrency=1)
    dest = tmp_path / "m.jpg"
    assert await downloader.fetch_to_file("https://i.pximg.net/m.jpg", dest) is True
    assert hosts == ["mirror.example.com", "i.pximg.net"]
    assert dest.read_bytes() == b"official"


async def test_downloader_prefers_mirror_when_it_works(tmp_path):
    hosts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        hosts.append(request.url.host)
        return httpx.Response(200, content=b"mirrored")

    downloader = ImageDownloader(_image_client(handler), mirror="mirror.example.com", concurrency=1)
    dest = tmp_path / "n.jpg"
    assert await downloader.fetch_to_file("https://i.pximg.net/n.jpg", dest) is True
    assert hosts == ["mirror.example.com"]
    assert dest.read_bytes() == b"mirrored"


async def test_downloader_fetch_bytes_returns_none_on_failure():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom")

    downloader = ImageDownloader(_image_client(handler), mirror=None, concurrency=1)
    assert await downloader.fetch_bytes("https://i.pximg.net/x.jpg") is None


async def test_downloader_does_not_leave_part_files(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    downloader = ImageDownloader(_image_client(handler), mirror=None, concurrency=1)
    await downloader.fetch_to_file("https://i.pximg.net/x.jpg", tmp_path / "x.jpg")
    assert list(tmp_path.iterdir()) == []
