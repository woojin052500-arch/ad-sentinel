import json
from pathlib import Path

import pytest

from ad_sentinel.detector import Detector, detect
from ad_sentinel.detector.detector import HIGH, SUSPECT
from ad_sentinel.detector.domains import suspicious_domain
from ad_sentinel.detector.keywords import find_keywords

FIXTURES = Path(__file__).parent / "fixtures"
START = "https://www.mois.go.kr/"


def _crawl(*pages):
    return {"meta": {"start_url": START, "config": {"include_subdomains": True}}, "pages": list(pages)}


def _page(url, *elements):
    return {"url": url, "final_url": url, "offsite_redirect": False, "elements": list(elements)}


def _rec(type_, content, selector="body > div", **extra):
    rec = {"type": type_, "content": content, "selector": selector, "frame_path": [], "frame_url": START}
    rec.update(extra)
    return rec


def _score(rec):
    return Detector(_crawl()).score(rec)


def test_real_mois_crawl_has_no_findings():
    sample = json.loads((FIXTURES / "mois_sample.json").read_text(encoding="utf-8"))
    result = detect(sample)
    assert result["findings"] == []
    assert len(result["external_domains"]) >= 50
    assert all(d["whitelisted"] for d in result["external_domains"])


@pytest.mark.parametrize("text", [
    "놀이터 안전",
    "웹 접근성인증",
    "(사)한국장애인단체총연합회 한국웹접근성인증평가원 웹 접근성 우수사이트 인증마크(WA인증마크)",
    "오피스텔 임대 안내",
    "오피니언",
    "행정안전부 유튜브 새창으로 열기",
])
def test_no_keyword_in_normal_text(text):
    assert find_keywords(text) == []


@pytest.mark.parametrize("rec", [
    _rec("text", "놀이터 안전"),
    _rec("link", "놀이터 안전", href="https://www.mois.go.kr/chd/sub/a06/play_2/screen.do"),
    _rec("hidden", "1. 국기에 대한 경례(맹세문 없음).mp3 2. 국기에 대한 경례(맹세문 성인남자).mp3",
         hidden_reasons=["display:none"], links=[]),
    _rec("link", "2. 국기에 대한 경례(맹세문 성인남자).mp3", hidden=True,
         href="https://www.mois.go.kr/cmm/fms/FileDown.do?atchFileId=FILE_000000000010854&fileSn=0"),
    _rec("link", "(사)한국장애인단체총연합회 한국웹접근성인증평가원 웹 접근성 우수사이트 인증마크(WA인증마크)",
         href="https://www.wa.or.kr/board/list.asp?BoardID=0006"),
    _rec("hidden", "본문 내용 바로가기 대메뉴 바로가기", hidden_reasons=["off-screen"], links=[START + "#container"]),
    _rec("hidden", "행정안전부 유튜브 새창으로 열기", hidden_reasons=["zero-size", "tiny-font"],
         links=["https://www.youtube.com/user/mopas"]),
    _rec("hidden", "", hidden_reasons=["display:none"], links=["https://www.facebook.com/mois"]),
    _rec("text", "강원랜드 카지노 규제 강화 방안 발표"),
    _rec("link", "카지노 산업 동향 보고서", href="https://www.korea.kr/news/policy.do"),
])
def test_known_false_positives_are_not_ads(rec):
    assert _score(rec) is None


def test_hidden_casino_link_is_high():
    f = _score(_rec("hidden", "온라인 카지노 바로가기", hidden_reasons=["display:none"],
                    links=["http://casino.invalid/"]))
    assert f["level"] == HIGH and f["category"] == "도박"
    kinds = {e["kind"] for e in f["evidence"]}
    assert {"keyword", "domain", "hidden", "external"} <= kinds


def test_obfuscated_keyword_is_detected():
    assert {k.word for k in find_keywords("카 지 노 가입 시 꽁.머.니 지급")} == {"카지노", "꽁머니"}
    f = _score(_rec("hidden", "카 지 노 바로가기", hidden_reasons=["same-color-as-background"]))
    assert f["level"] == HIGH


def test_visible_comment_with_several_keywords_is_high():
    f = _score(_rec("text", "먹튀 없는 안전놀이터 가입코드 777"))
    assert f["level"] == HIGH
    assert {e["label"] for e in f["evidence"]} >= {"도박 키워드 '먹튀'", "도박 키워드 '안전놀이터'"}


def test_suspicious_domain_link_needs_review():
    f = _score(_rec("link", "바로가기", href="http://toto777.xyz/"))
    assert f["level"] == SUSPECT


def test_suspicious_domain_rules():
    assert suspicious_domain("toto777.xyz") == "도박"
    assert suspicious_domain("my-casino365.com") == "도박"
    assert suspicious_domain("free-porn.site") == "성인"
    assert suspicious_domain("www.alphabet.com") is None
    assert suspicious_domain("www.totorial.com") is None


def test_common_header_is_grouped_across_pages():
    ad = _rec("hidden", "토토사이트 추천", selector="#header > span", hidden_reasons=["tiny-font"])
    pages = [_page(START + f"page{i}.do", dict(ad)) for i in range(3)]
    result = detect(_crawl(*pages))
    assert len(result["findings"]) == 1
    f = result["findings"][0]
    assert f["page_count"] == 3
    assert f["location_label"] == "3개 페이지에서 발견"


def test_link_inside_hidden_ad_is_not_reported_twice():
    parent = _rec("hidden", "카지노 바로가기", selector="#content > div", hidden_reasons=["display:none"],
                  links=["http://casino.invalid/"])
    child = _rec("link", "카지노 바로가기", selector="#content > div > a", hidden=True, href="http://casino.invalid/")
    result = detect(_crawl(_page(START, parent, child)))
    assert [f["selector"] for f in result["findings"]] == ["#content > div"]


def test_text_inside_tiny_iframe_counts_as_hidden():
    iframe = _rec("iframe", "", selector="#content > iframe", src="https://www.mois.go.kr/ad.html",
                  hidden=True, hidden_reasons=["tiny-size"])
    inner = _rec("text", "홀덤 입금 보너스 100%", selector="body > p", frame_path=["#content > iframe"])
    result = detect(_crawl(_page(START, iframe, inner)))
    f = result["findings"][0]
    assert f["level"] == HIGH
    assert any(e["label"] == "숨겨진 iframe 내부" for e in f["evidence"])
