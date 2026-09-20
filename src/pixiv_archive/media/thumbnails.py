import io
import logging
from pathlib import Path

from PIL import Image, UnidentifiedImageError

logger = logging.getLogger(__name__)

THUMB_LONG_EDGE = 400
THUMB_QUALITY = 82


def is_valid_image(data: bytes) -> bool:
    """Verify that downloaded bytes decode into a complete image.

    Uses ``load()`` (full decode) rather than ``verify()`` because the latter
    only checks container headers for JPEG and would accept truncated files.
    """
    try:
        with Image.open(io.BytesIO(data)) as image:
            image.load()
        return True
    except (UnidentifiedImageError, OSError, ValueError):
        return False


def generate_thumb(src: Path, dest: Path, *, long_edge: int = THUMB_LONG_EDGE) -> bool:
    """Create a WebP thumbnail; returns False when the source is unusable."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        with Image.open(src) as image:
            image.load()
            if image.mode not in ("RGB", "RGBA"):
                image = image.convert("RGBA" if "A" in image.getbands() else "RGB")
            else:
                image = image.copy()
            if max(image.size) > long_edge:
                image.thumbnail((long_edge, long_edge), Image.Resampling.LANCZOS)
            image.save(dest, format="WEBP", quality=THUMB_QUALITY, method=4)
        return True
    except (UnidentifiedImageError, OSError, ValueError):
        logger.warning("thumbnail generation failed for %s", src, exc_info=True)
        return False
