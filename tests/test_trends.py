import functools
import http.server
import os
import threading
import unicodedata
from pathlib import Path

import pytest

import demo_server
from ad_sentinel.config import CrawlConfig
from ad_sentinel.crawler import Crawler
from ad_sentinel.detector import Detector, detect
from ad_sentinel.detector.detector import CLOAKING, HIDDEN, SEARCH_LIST, STUFFING, stuffing_stats
from ad_sentinel.detector.keywords import find_contact, find_keywords, is_prevention_context
from ad_sentinel.detector.variants import CONFUSABLES, CONFUSABLES_FILE, analyze, evidence_label, normalize

FIXTURES = Path(__file__).parent / "fixtures"
START = "https://www.example.go.kr/"


class DemoServer:
    def __init__(self):
        os.environ["NO_PROXY"] = "127.0.0.1,localhost"
        os.environ["no_proxy"] = "127.0.0.1,localhost"
        self.requests: list[tuple[str, str, str]] = []
        requests = self.requests

        class Handler(demo_server.DemoHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                requests.append((self.path, self.headers.get("User-Agent", ""), self.headers.get("Referer", "")))
                super().do_GET()

        self.server = http.server.ThreadingHTTPServer(
            ("127.0.0.1", 0), functools.partial(Handler, directory=str(demo_server.SITE_DIR)))
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.server.server_port}/"

    def crawl(self, path, **options):
        values = dict(start_url=self.base + path, max_pages=20, delay_sec=0, render_wait_ms=300,
                      networkidle_timeout_ms=1500, use_sitemap=False)
        values.update(options)
        try:
            return Crawler(CrawlConfig(**values)).run()
        finally:
            self.server.shutdown()


@pytest.fixture(scope="module")
def trends():
    crawl = DemoServer().crawl("trends/index.html")
    return crawl, detect(crawl)


def _on(report, page):
    return [f for f in report["findings"] if any(p.endswith("/" + page) for p in f["pages"])]


def test_search_list_pollution(trends):
    _, report = trends
    found = [f for f in _on(report, "search.html") if f["pattern"] == SEARCH_LIST]
    contents = sorted(f["content"] for f in found)
    assert contents == ["마약 구매 텔레그램 @drug_kr24", "아이스 작대기 판매 텔레 @ice_seoul77",
                        "테더 환전 대행 t.me/usdt_fast"]
    assert all(f["pattern_label"] == "검색어 목록 오염" and f["level"] == "high" for f in found)
    labels = {e["label"] for f in found for e in f["evidence"]}
    assert "사이트 검색어 목록(실시간 검색어)에 올라 있음" in labels
    assert "사이트 검색어 목록(최근 검색어)에 올라 있음" in labels
    assert not any("여권" in f["content"] or "주민등록" in f["content"] for f in report["findings"])


def test_normal_pages_and_prevention_notice_have_no_findings(trends):
    _, report = trends
    assert _on(report, "index.html") == []
    assert _on(report, "notice.html") == []


def test_keyword_stuffing_page(trends):
    _, report = trends
    found = _on(report, "spam.html")
    stuffing = [f for f in found if f["pattern"] == STUFFING]
    assert len(stuffing) == 1
    st = stuffing[0]["stuffing"]
    assert st["count"] >= 50 and st["kinds"] >= 10 and st["list_lines"] >= 8 and st["merged"] >= 8
    assert "해킹 생성 페이지 의심" in stuffing[0]["content"]
    assert not any(f["pattern"] == "visible" and f["type"] == "text" for f in found)


def test_hidden_spots_meta_og_alt_noscript(trends):
    _, report = trends
    by_selector = {f["selector"]: f for f in _on(report, "spots.html")}
    meta = by_selector['meta[name="description"]']
    og = by_selector['meta[property="og:description"]']
    alt = next(f for f in by_selector.values() if f["type"] == "alt")
    noscript = next(f for f in by_selector.values() if f["type"] == "noscript")
    assert "검색엔진용 정보(description)에만 들어 있음" in [e["label"] for e in meta["evidence"]]
    assert "검색엔진용 정보(og:description)에만 들어 있음" in [e["label"] for e in og["evidence"]]
    assert "이미지 대체 텍스트(alt)에 들어 있음" in [e["label"] for e in alt["evidence"]]
    assert any(e["label"].startswith("noscript 안") for e in noscript["evidence"])
    assert noscript["urls"] == ["https://ice-shop.invalid/"]
    assert all(f["pattern"] == HIDDEN for f in (meta, og, alt, noscript))


def test_new_categories_on_board(trends):
    _, report = trends
    found = _on(report, "board.html")
    assert sorted(f["category"] for f in found) == ["대포통장", "마약", "불법환전", "작업대출"]
    assert all(f["level"] == "high" for f in found)
    telegram = [e["label"] for f in found for e in f["evidence"] if e["label"].startswith("텔레그램 ID")]
    assert "텔레그램 ID 포함 (텔그 : ice_seoul)" in telegram and "텔레그램 ID 포함 (TG@usdt_fast)" in telegram


@pytest.fixture(scope="module")
def cloak_run():
    server = DemoServer()
    crawl = server.crawl("cloak/index.html", max_pages=1, cloaking_check="suspect")
    return crawl, detect(crawl), server.requests


def test_cloaking_is_found_for_each_disguise(cloak_run):
    crawl, report, requests = cloak_run
    found = {f["cloaking"]["profile"]: f for f in report["findings"] if f["pattern"] == CLOAKING}
    assert set(found) == {"googlebot", "google_referer", "mobile"}
    assert all(f["pattern_label"] == "클로킹 의심" and f["level"] == "high" for f in found.values())
    bot = found["googlebot"]
    assert bot["cloaking"]["only_in"] == "구글봇으로 볼 때만 나타남"
    assert "카지노" in bot["cloaking"]["new_keywords"] and "바카라" in bot["cloaking"]["new_keywords"]
    assert any(e["label"].startswith("구글봇으로 볼 때만 나타남: 광고 키워드") for e in bot["evidence"])
    assert found["google_referer"]["cloaking"]["redirects"] == ["https://toto-win.invalid/?ref=gov"]
    assert any("구글 검색 경유 접속일 때만 다른 사이트로 이동: toto-win.invalid" == e["label"]
               for e in found["google_referer"]["evidence"])
    assert "슬롯사이트" in found["mobile"]["cloaking"]["new_keywords"]
    assert any(e["label"] == "모바일로 볼 때만 외부 링크: slot-mobile.invalid" for e in found["mobile"]["evidence"])
    served = {demo_server.cloak_page(ua, ref) for path, ua, ref in requests if path.startswith("/cloak/")}
    assert served == {"index.html", "bot.html", "google.html", "mobile.html"}
    assert any("Googlebot" in ua for _, ua, _ in requests)
    assert any("google.com" in ref for _, _, ref in requests)
    assert crawl["pages"][0]["cloaking"]["reason"] == "첫 페이지"


def test_cloaking_check_is_off_by_default():
    server = DemoServer()
    crawl = server.crawl("cloak/index.html", max_pages=1)
    assert "cloaking" not in crawl["pages"][0]
    assert detect(crawl)["findings"] == []
    assert not any("Googlebot" in ua for _, ua, _ in server.requests)


def test_same_content_everywhere_is_not_cloaking():
    snap = {"title": "복지 안내", "text": "기초연금 신청 안내", "links": [], "redirects": [], "hidden": [], "error": None}
    profiles = [dict(snap, key=k, label=l, only_in=o) for k, l, o in
                [("pc", "일반 PC", ""), ("googlebot", "구글봇", "구글봇으로 볼 때만 나타남"),
                 ("mobile", "모바일", "모바일로 접속할 때만 나타남")]]
    profiles[2]["text"] = "기초연금 신청 안내 모바일 메뉴 전체 보기 로그인 고객센터 바로가기 사이트맵"
    page = {"url": START, "final_url": START, "elements": [], "frames": [], "cloaking": {"profiles": profiles}}
    crawl = {"meta": {"start_url": START, "config": {"include_subdomains": True}}, "pages": [page]}
    assert detect(crawl)["findings"] == []


@pytest.mark.parametrize("ua,referer,page", [
    ("Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)", "", "bot.html"),
    ("Mozilla/5.0 (Windows NT 10.0) Chrome/126", "https://www.google.com/", "google.html"),
    ("Mozilla/5.0 (Linux; Android 14) Mobile Safari", "", "mobile.html"),
    ("Mozilla/5.0 (Windows NT 10.0) Chrome/126", "", "index.html"),
])
def test_demo_cloak_page_selection(ua, referer, page):
    assert demo_server.cloak_page(ua, referer) == page


@pytest.mark.parametrize("text,kind", [
    ("텔레그램 @toto777", "telegram"), ("텔레 toto777", "telegram"), ("텔그 : ice_seoul", "telegram"),
    ("t.me/drugshop", "telegram"), ("TG@ice777", "telegram"), ("tg: ice77", "telegram"),
    ("텔레그램ID: ice_seoul", "telegram"), ("문의 @bitcoin_ex", "contact"), ("카톡 loan24", "contact"),
    ("010-1234-5678", "contact"),
])
def test_contact_patterns(text, kind):
    assert find_contact(text)[0] == kind


@pytest.mark.parametrize("text", ["Tele Sales 팀", "TG Company", "텔레비전 시청 안내", "호텔 abc123 예약",
                                  "문의 help@mois.go.kr", "hotel abc@naver.com"])
def test_contact_false_positives(text):
    assert find_contact(text) is None


@pytest.mark.parametrize("text", [
    "대마도 여행 안내", "야바위 놀이 체험", "마약김밥 맛집 소개", "통장 개설 안내", "환전 수수료 안내",
    "법인통장 개설 서류", "대출 금리 비교 안내", "공 던지기 체험 교실",
])
def test_new_keywords_do_not_flag_normal_text(text):
    crawl = {"meta": {"start_url": START, "config": {"include_subdomains": True}},
             "pages": [{"url": START, "final_url": START, "elements": [
                 {"type": "text", "content": text, "selector": "#c", "frame_path": [], "frame_url": START}]}]}
    assert detect(crawl)["findings"] == []


@pytest.mark.parametrize("text", [
    "불법 스포츠 도박과 온라인 카지노, 바카라 같은 사행성 게임이 퍼지고 있습니다.",
    "필로폰, 대마초 등 마약류 투약과 거래는 엄중히 처벌됩니다.",
    "토토사이트 가입을 권유하는 광고는 불법이며 신고센터에 신고하세요.",
])
def test_prevention_context_is_not_an_ad(text):
    assert is_prevention_context(text)
    assert Detector({"meta": {"start_url": START}}).score(
        {"type": "text", "content": text, "selector": "#c", "frame_path": [], "frame_url": START}) is None


def test_prevention_context_does_not_hide_contact_ads():
    rec = {"type": "text", "content": "불법 아님! 안전한 토토사이트 카지노 텔레그램 @safe_toto77", "selector": "#c",
           "frame_path": [], "frame_url": START}
    assert Detector({"meta": {"start_url": START}}).score(rec)["level"] == "high"


def test_stuffing_needs_repetition_and_density():
    long_notice = (FIXTURES / "trends" / "notice.html").read_text(encoding="utf-8")
    assert stuffing_stats(long_notice) is None
    assert stuffing_stats("카지노 바카라 토토사이트 먹튀 슬롯사이트 꽁머니\n" * 10)["list_lines"] == 10


def test_confusables_table_is_loaded_from_unicode_file():
    header = CONFUSABLES_FILE.read_text(encoding="utf-8-sig").splitlines()[:8]
    assert header[0] == "# confusables.txt" and any("Unicode" in line for line in header)
    assert (CONFUSABLES_FILE.parent / "LICENSE-UNICODE.txt").read_text(encoding="utf-8").startswith(
        "UNICODE LICENSE V3")
    assert len(CONFUSABLES) > 1000
    for source, target in CONFUSABLES.items():
        assert not source.isascii() and target.isascii() and target.isalpha()
        assert unicodedata.category(source).startswith("L") or unicodedata.category(source) == "Nl"
        assert not ("가" <= source <= "힣" or "ᄀ" <= source <= "ᇿ" or "㄰" <= source <= "㆏")


@pytest.mark.parametrize("text,word", [
    ("casinо", "casino"), ("саsіnо", "casino"), ("cαsino", "casino"), ("ꮯasino", "casino"),
    ("bαccαrαt", "baccarat"), ("рогn", "porn"), ("Ꮲorn", "porn"), ("vіаgrа", "viagra"),
])
def test_confusable_letters_use_uts39(text, word):
    hit = next(h for h in analyze(text) if h.keyword.word == word)
    assert hit.method == "confusable" and hit.weight == hit.keyword.weight
    assert evidence_label(hit).endswith(f"변형 표기: {text} → {word} (닮은꼴 문자, UTS #39)")


@pytest.mark.parametrize("text", [
    "0O 1l I| rn m", "Привет, мир! Добро пожаловать", "Γειά σου κόσμε", "你好世界 こんにちは",
    "한글 ㅣ ㅇ ㅡ 테스트", "제Ⅱ장 3×4 ○○시",
])
def test_confusables_do_not_create_false_positives(text):
    assert analyze(text) == []
    assert normalize("0O 1l I|")[0] == "0O 1l I|"
