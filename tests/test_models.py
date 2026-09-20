from pixiv_archive.pixiv.models import BookmarkPage, IllustDetail, UgoiraMetadata


def test_bookmark_page_parses_illust_urls_single_page():
    payload = {
        "illusts": [
            {
                "id": 147217442,
                "title": "t",
                "type": "illust",
                "page_count": 1,
                "width": 100,
                "height": 200,
                "x_restrict": 0,
                "sanity_level": 2,
                "illust_ai_type": 2,
                "total_view": 5,
                "total_bookmarks": 6,
                "create_date": "2026-07-15T07:11:25+09:00",
                "user": {"id": 73804603, "name": "魚辺ン", "account": "3227332346"},
                "tags": [{"name": "R-18", "translated_name": None}],
                "meta_single_page": {"original_image_url": "https://i.pximg.net/orig.png"},
                "image_urls": {"square_medium": "https://i.pximg.net/sq.jpg"},
            }
        ],
        "next_url": "https://app-api.pixiv.net/v1/user/bookmarks/illust?user_id=1&max_bookmark_id=999",
    }
    page = BookmarkPage.model_validate(payload)
    assert page.next_bookmark_id == 999
    illust = page.illusts[0]
    assert illust.pid == 147217442
    assert illust.page_count == 1
    assert illust.original_urls == ["https://i.pximg.net/orig.png"]
    assert illust.preview_url == "https://i.pximg.net/sq.jpg"
    assert illust.author.id == 73804603
    assert illust.tags[0].name == "R-18"


def test_bookmark_page_parses_meta_pages():
    payload = {
        "illusts": [
            {
                "id": 1,
                "title": "multi",
                "type": "illust",
                "page_count": 2,
                "user": {"id": 1, "name": "a"},
                "meta_pages": [
                    {"image_urls": {"original": "https://i.pximg.net/p0.jpg"}},
                    {"image_urls": {"original": "https://i.pximg.net/p1.jpg"}},
                ],
                "image_urls": {},
            }
        ],
        "next_url": None,
    }
    page = BookmarkPage.model_validate(payload)
    assert page.next_bookmark_id is None
    assert page.illusts[0].original_urls == [
        "https://i.pximg.net/p0.jpg",
        "https://i.pximg.net/p1.jpg",
    ]


def test_bookmark_page_next_url_without_cursor():
    payload = {"illusts": [], "next_url": "https://app-api.pixiv.net/x?user_id=1"}
    assert BookmarkPage.model_validate(payload).next_bookmark_id is None


def test_illust_detail_parses():
    payload = {
        "illust": {
            "id": 5,
            "title": "d",
            "type": "ugoira",
            "page_count": 1,
            "user": {"id": 2, "name": "b"},
            "meta_single_page": {"original_image_url": "https://i.pximg.net/u0.jpg"},
            "image_urls": {},
        }
    }
    detail = IllustDetail.model_validate(payload)
    assert detail.illust.pid == 5
    assert detail.illust.type == "ugoira"


def test_ugoira_metadata_parses():
    payload = {
        "ugoira_metadata": {
            "zip_urls": {"medium": "https://i.pximg.net/ugoira600x600.zip"},
            "frames": [{"file": "000000.jpg", "delay": 100}],
        }
    }
    meta = UgoiraMetadata.from_response(payload)
    assert meta.zip_url == "https://i.pximg.net/ugoira600x600.zip"
    assert meta.frames[0].delay == 100
