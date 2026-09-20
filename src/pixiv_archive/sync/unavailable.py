from pixiv_archive.pixiv.models import Illust as PixivIllust

_PLACEHOLDER_MARKER = "s.pximg.net/common/images/limit_"


def is_unavailable(illust: PixivIllust) -> bool:
    """True when pixiv returns a placeholder stub for a deleted/private work.

    pixiv keeps the bookmark entry but blanks everything out: user id 0 and
    every image URL points at s.pximg.net/common/images/limit_*.
    """
    if illust.user.id == 0:
        return True
    return any(_PLACEHOLDER_MARKER in url for url in _all_urls(illust))


def _all_urls(illust: PixivIllust) -> list[str]:
    urls = list(illust.original_urls)
    urls.extend(str(value) for value in illust.image_urls.values())
    for page in illust.meta_pages:
        urls.extend(str(value) for value in (page.get("image_urls") or {}).values())
    return urls
