import json

PLACEHOLDER_MARKER = "s.pximg.net/common/images/limit_"


def is_placeholder_url(url: str) -> bool:
    """True when the url points at pixiv's deleted/private placeholder image."""
    return PLACEHOLDER_MARKER in url


def preview_url_from_meta(meta_json: str | None) -> str | None:
    """Pick the preview image url from a stored illust ``meta_json``.

    ``medium`` keeps the original aspect ratio (long edge 540); ``square_medium``
    is a 1:1 center crop, so it is only a fallback.
    """
    if not meta_json:
        return None
    try:
        payload = json.loads(meta_json)
    except ValueError:
        return None
    urls = payload.get("image_urls") or {}
    return urls.get("medium") or urls.get("square_medium")
