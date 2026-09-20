import io

from PIL import Image

from pixiv_archive.media.thumbnails import (
    THUMB_LONG_EDGE,
    generate_thumb,
    is_valid_image,
)


def _image_bytes(size=(1200, 800), fmt="JPEG") -> bytes:
    image = Image.new("RGB", size, color=(120, 60, 30))
    buffer = io.BytesIO()
    image.save(buffer, format=fmt)
    return buffer.getvalue()


def test_is_valid_image_true_for_jpeg():
    assert is_valid_image(_image_bytes()) is True


def test_is_valid_image_false_for_garbage():
    assert is_valid_image(b"not an image at all") is False


def test_is_valid_image_false_for_truncated():
    data = _image_bytes(size=(800, 800))
    assert is_valid_image(data[: len(data) // 3]) is False


def test_generate_thumb_scales_long_edge(tmp_path):
    src = tmp_path / "a.jpg"
    src.write_bytes(_image_bytes(size=(2400, 1200)))
    dest = tmp_path / "thumb.webp"
    assert generate_thumb(src, dest) is True
    assert dest.exists()
    with Image.open(dest) as img:
        assert img.format == "WEBP"
        assert max(img.size) == THUMB_LONG_EDGE
        assert img.size == (THUMB_LONG_EDGE, THUMB_LONG_EDGE // 2)


def test_generate_thumb_keeps_small_images(tmp_path):
    src = tmp_path / "small.jpg"
    src.write_bytes(_image_bytes(size=(200, 100)))
    dest = tmp_path / "thumb.webp"
    assert generate_thumb(src, dest) is True
    with Image.open(dest) as img:
        assert img.size == (200, 100)


def test_generate_thumb_returns_false_for_invalid(tmp_path):
    src = tmp_path / "bad.jpg"
    src.write_bytes(b"garbage")
    dest = tmp_path / "thumb.webp"
    assert generate_thumb(src, dest) is False
    assert not dest.exists()


def test_generate_thumb_preserves_alpha_as_rgb(tmp_path):
    image = Image.new("RGBA", (800, 600), color=(10, 20, 30, 128))
    src = tmp_path / "alpha.png"
    image.save(src, format="PNG")
    dest = tmp_path / "thumb.webp"
    assert generate_thumb(src, dest) is True
    with Image.open(dest) as opened:
        assert opened.mode in ("RGB", "RGBA")
