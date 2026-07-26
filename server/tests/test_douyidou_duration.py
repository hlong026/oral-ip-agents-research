"""Douyidou response compatibility."""


def test_extracts_duration_from_douyin_other_payload() -> None:
    from app.providers.douyidou import DouyidouParser

    duration = DouyidouParser._extract_duration(
        {
            "type": "video",
            "platform": 1,
            "other": {"duration": 325705},
        }
    )

    assert duration == 325.705
