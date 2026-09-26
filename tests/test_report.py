import csv
import json

from ad_sentinel.report import export_csv, export_html, export_json

REPORT = {
    "meta": {"start_url": "https://www.example.go.kr/", "page_count": 3, "detected_at": "2026-09-26T12:00:00",
             "version": "0.1.0", "mode": "list"},
    "summary": {"findings": 1, "high": 0, "suspect": 1, "by_pattern": {"악용 가능 지점": 1}},
    "external_domains": [{"host": "bet.invalid", "count": 1, "whitelisted": False}],
    "findings": [{
        "id": 1, "level": "suspect", "level_label": "검토 필요", "score": 5, "pattern": "reflection_surface",
        "pattern_label": "악용 가능 지점", "category": "도박", "type": "text",
        "content": "'카지노 규제' 검색 결과 <script>", "selector": "#result > p", "frame_path": ["#f"],
        "frame_url": "", "urls": [], "hidden_reasons": [], "rect": None,
        "evidence": [{"kind": "keyword", "label": "도박 키워드 '카지노'", "points": 3}],
        "reflected_params": [{"name": "q", "value": "카지노 규제"}],
        "advice": "입력값을 그대로 출력하지 않도록 조치를 권장합니다.",
        "pages": ["https://www.example.go.kr/search.do?q=x"], "page_count": 1, "location_label": "",
    }],
}


def test_csv_opens_in_korean_excel(tmp_path):
    path = export_csv(REPORT, tmp_path / "r.csv")
    assert path.read_bytes().startswith(b"\xef\xbb\xbf")
    rows = list(csv.reader(open(path, encoding="utf-8-sig")))
    assert rows[0][:4] == ["번호", "판정", "유형", "분류"]
    assert rows[1][1:4] == ["검토 필요", "악용 가능 지점", "도박"]
    assert "q=카지노 규제" in rows[1]
    assert "#f ▶ #result > p" in rows[1]


def test_html_report_escapes_content(tmp_path):
    text = export_html(REPORT, tmp_path / "r.html").read_text(encoding="utf-8")
    assert "&lt;script&gt;" in text and "<script>" not in text
    assert "URL 목록 점검" in text and "악용 가능 지점" in text
    assert "입력값을 그대로 출력하지 않도록" in text and "bet.invalid" in text


def test_json_roundtrip(tmp_path):
    path = export_json(REPORT, tmp_path / "r.json")
    assert json.loads(path.read_text(encoding="utf-8")) == REPORT
