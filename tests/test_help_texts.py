from ad_sentinel.help_texts import COLUMNS, QUICK_START, SETTINGS, UNCHECKED, as_markdown, estimate_text, tooltip_text

SETTING_KEYS = {"max_pages", "max_depth", "enter_gate", "sitemap", "own_site", "delay", "page_timeout", "show_browser",
                "detail_log"}


def test_every_setting_has_three_line_help():
    assert set(SETTINGS) == SETTING_KEYS
    for item in SETTINGS.values():
        text = tooltip_text(item)
        assert text.startswith("무엇인가요: ") and "\n언제 바꾸나요: " in text and "\n추천: " in text


def test_result_help_covers_levels_and_patterns():
    assert {"level", "pattern", "score"} <= set(COLUMNS)
    for label in ("불법광고 의심", "검토 필요"):
        assert label in COLUMNS["level"].what
    for label in ("URL 파라미터 반사", "숨김 광고", "노출 광고", "악용 가능 지점", "자동 이동"):
        assert label in COLUMNS["pattern"].what
    assert "5점" in COLUMNS["score"].when
    assert "왜 확인해야 하나요" in tooltip_text(UNCHECKED) and "iframe" in UNCHECKED.what


def test_key_explanations():
    assert "2단계" in SETTINGS["max_depth"].what
    assert "다 불러와지지 않았을 수 있습니다" in SETTINGS["page_timeout"].when
    assert "1~3초" in SETTINGS["delay"].recommend
    assert "robots.txt는" in SETTINGS["own_site"].what and "권한" in SETTINGS["own_site"].when
    assert "비워 두면 자동으로" in SETTINGS["sitemap"].when
    for word in ("로그인", "회원가입", "결제", "삭제", "신고"):
        assert word in SETTINGS["enter_gate"].what
    assert "30페이지 약 2분" in SETTINGS["max_pages"].when


def test_estimate_text():
    assert estimate_text(5) == "1분 이내"
    assert estimate_text(30) == "약 2분"
    assert estimate_text(1000) == "약 1시간 23분"
    assert estimate_text(720) == "약 1시간"


def test_markdown_for_manual():
    md = as_markdown()
    assert [name for name, _ in QUICK_START] == ["주소 입력", "점검 시작", "결과 확인"]
    for item in [*SETTINGS.values(), *COLUMNS.values(), UNCHECKED]:
        assert f"### {item.title}" in md
