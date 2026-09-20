from fakes import make_illust, make_stub_illust
from pixiv_archive.sync.unavailable import is_unavailable


def test_stub_by_url_is_unavailable():
    illust = make_stub_illust(123)
    assert is_unavailable(illust) is True


def test_stub_by_zero_author_is_unavailable():
    illust = make_illust(456, user={"id": 0, "name": "", "account": ""})
    assert is_unavailable(illust) is True


def test_normal_illust_is_available():
    assert is_unavailable(make_illust(789)) is False


def test_placeholder_in_meta_pages_is_detected():
    illust = make_illust(
        790,
        meta_pages=[
            {
                "image_urls": {
                    "original": "https://s.pximg.net/common/images/limit_mypixiv_360.png"
                }
            }
        ],
    )
    assert is_unavailable(illust) is True
