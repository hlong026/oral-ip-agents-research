from app.providers.url_resolver import Platform, resolve_input


def test_resolve_douyin_jingxuan_search_url_to_video_url() -> None:
    raw = (
        "https://www.douyin.com/jingxuan/search/%E4%B9%A1%E5%A2%85"
        "?aid=f7b8b55d-ee2a-4ad6-9a06-b98aaa624e75"
        "&modal_id=7636744762704744891&type=general"
    )

    resolved = resolve_input(raw)

    assert resolved.platform == Platform.DOUYIN
    assert resolved.url == "https://www.douyin.com/jingxuan?modal_id=7636744762704744891"


def test_resolve_douyin_share_text_to_embedded_short_url() -> None:
    raw = (
        "8.71 g@b.AG 02/06 vsE:/ :1pm 我为什么做乡墅这个行业"
        "# 乡墅 # 创业 # 自建房 # 乡村别墅 # 别墅  "
        "https://v.douyin.com/GYXP_jQ3azg/ 复制此链接，打开Dou音搜索，直接观看视频！"
    )

    resolved = resolve_input(raw)

    assert resolved.platform == Platform.DOUYIN
    assert resolved.url == "https://v.douyin.com/GYXP_jQ3azg/"
