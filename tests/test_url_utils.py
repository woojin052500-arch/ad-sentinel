from ad_sentinel.crawler.url_utils import is_crawlable, is_same_site, normalize_url


def test_normalize_relative_and_fragment():
    assert normalize_url("../b.html#top", "https://Www.Example.go.kr/a/c.html") == "https://www.example.go.kr/b.html"


def test_normalize_keeps_query_and_drops_default_port():
    assert normalize_url("http://example.go.kr:80/board?nttId=1") == "http://example.go.kr/board?nttId=1"
    assert normalize_url("https://example.go.kr:8443") == "https://example.go.kr:8443/"


def test_normalize_skips_non_http():
    for bad in ["javascript:void(0)", "mailto:a@b.kr", "tel:010", "#top", "", "ftp://x.kr/"]:
        assert normalize_url(bad, "https://example.go.kr/") == ""


def test_same_site():
    start = "https://www.example.go.kr/"
    assert is_same_site("https://www.example.go.kr/a", start)
    assert is_same_site("https://board.example.go.kr/a", start)
    assert is_same_site("https://example.go.kr/a", start)
    assert not is_same_site("https://board.example.go.kr/a", start, include_subdomains=False)
    assert not is_same_site("https://example.go.kr.evil.com/", start)
    assert not is_same_site("https://notexample.go.kr/", start)


def test_crawlable():
    assert is_crawlable("https://x.kr/board/list.do")
    assert is_crawlable("https://x.kr/v1.2/page")
    assert not is_crawlable("https://x.kr/file/report.PDF")
    assert not is_crawlable("https://x.kr/a.hwp")
