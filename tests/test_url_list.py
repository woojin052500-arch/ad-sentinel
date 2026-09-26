import csv
import functools
import http.server
import os
import threading
import zipfile
from pathlib import Path

from ad_sentinel.config import CrawlConfig
from ad_sentinel.crawler import Crawler
from ad_sentinel.detector import detect
from ad_sentinel.url_list import load_url_list

REFLECT_DIR = Path(__file__).parent / "fixtures" / "reflect"
SPAM = "http://old.gongdan.go.kr/home.jsp?play=%EB%B0%94%EC%B9%B4%EB%9D%BC%EB%B6%84%EC%84%9D"


def test_txt_one_url_per_line(tmp_path):
    path = tmp_path / "urls.txt"
    path.write_text("# 점검 목록\nhttps://www.example.go.kr/a.do\n\nwww.example.go.kr/b.do\n"
                    "https://www.example.go.kr/a.do#top\n메모\n" + SPAM + "\n", encoding="utf-8")
    assert load_url_list(path) == ["https://www.example.go.kr/a.do", "http://www.example.go.kr/b.do", SPAM]


def test_search_console_csv_korean_header(tmp_path):
    path = tmp_path / "페이지.csv"
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["상위 페이지", "클릭수", "노출수", "CTR", "게재순위"])
        w.writerow([SPAM, "0", "152", "0%", "8.4"])
        w.writerow(["https://www.example.go.kr/", "31", "900", "3.4%", "2.1"])
    assert load_url_list(path) == [SPAM, "https://www.example.go.kr/"]


def test_csv_saved_by_korean_excel_cp949(tmp_path):
    path = tmp_path / "list.csv"
    path.write_bytes("주소,비고\nhttps://www.example.go.kr/x.do,확인 필요\n".encode("cp949"))
    assert load_url_list(path) == ["https://www.example.go.kr/x.do"]


def test_tab_separated_utf16_from_excel(tmp_path):
    path = tmp_path / "list.txt"
    path.write_text("URL\t메모\nhttps://www.example.go.kr/y.do\t메모\n", encoding="utf-16")
    assert load_url_list(path) == ["https://www.example.go.kr/y.do"]


def test_search_console_zip_export(tmp_path):
    path = tmp_path / "export.zip"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("쿼리.csv", "인기 검색어,클릭수\n바카라분석,0\n".encode("utf-8-sig"))
        z.writestr("차트.csv", "날짜,클릭수\n2026-09-01,3\n".encode("utf-8-sig"))
        z.writestr("페이지.csv", f"상위 페이지,클릭수\n{SPAM},0\n".encode("utf-8-sig"))
    assert load_url_list(path) == [SPAM]


def test_list_mode_checks_only_listed_urls():
    os.environ["NO_PROXY"] = "127.0.0.1,localhost"
    os.environ["no_proxy"] = "127.0.0.1,localhost"

    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=str(REFLECT_DIR)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_port}/"
    urls = [base + "home.html?play=%EB%B0%94%EC%B9%B4%EB%9D%BC%EB%B6%84%EC%84%9D", base + "index.html"]
    progress = []
    try:
        config = CrawlConfig(url_list=urls, delay_sec=0, render_wait_ms=300, networkidle_timeout_ms=2000)
        crawl = Crawler(config, on_progress=lambda d, t, u: progress.append((d, t))).run()
    finally:
        server.shutdown()

    assert crawl["meta"]["mode"] == "list"
    assert crawl["meta"]["seed_urls"] == urls
    assert [p["url"] for p in crawl["pages"]] == urls
    assert all(p["found_on"] == "URL 목록" for p in crawl["pages"])
    assert progress[0] == (0, 2) and progress[-1] == (2, 2)
    report = detect(crawl)
    assert report["meta"]["mode"] == "list"
    assert {f["pattern_label"] for f in report["findings"]} == {"URL 파라미터 반사"}
