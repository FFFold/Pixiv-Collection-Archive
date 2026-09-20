from pixiv_archive.web.files import (
    build_etag,
    file_not_modified,
    parse_range,
    placeholder_svg,
    resolve_thumb,
)

CONTENT = b"0123456789"


def test_parse_range_returns_bounds():
    assert parse_range("bytes=0-4", 10) == (0, 4)
    assert parse_range("bytes=5-", 10) == (5, 9)
    assert parse_range("bytes=-3", 10) == (7, 9)


def test_parse_range_rejects_invalid():
    assert parse_range(None, 10) is None
    assert parse_range("bytes=abc", 10) is None
    assert parse_range("items=0-1", 10) is None
    assert parse_range("bytes=20-30", 10) is None
    assert parse_range("bytes=5-2", 10) is None


def test_build_etag_is_stable(tmp_path):
    path = tmp_path / "f.bin"
    path.write_bytes(CONTENT)
    a = build_etag(path)
    b = build_etag(path)
    assert a == b
    assert a.startswith('"')


def test_file_not_modified():
    etag = '"abc"'
    assert file_not_modified(etag, etag) is True
    assert file_not_modified('"other"', etag) is False
    assert file_not_modified(None, etag) is False


def test_resolve_thumb_prefers_webp(tmp_path):
    root = tmp_path
    work = root / "1"
    (work / "original").mkdir(parents=True)
    assert resolve_thumb(root, 1) is None
    (work / "preview.jpg").write_bytes(CONTENT)
    assert resolve_thumb(root, 1) == work / "preview.jpg"
    (work / "thumb.webp").write_bytes(CONTENT)
    assert resolve_thumb(root, 1) == work / "thumb.webp"


def test_placeholder_svg_for_missing(tmp_path):
    svg = placeholder_svg(1)
    assert "<svg" in svg
    assert "1" in svg
