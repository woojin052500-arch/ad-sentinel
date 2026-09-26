import pytest

tk = pytest.importorskip("tkinter")

from ad_sentinel.detector import detect  # noqa: E402

START = "https://www.example.go.kr/"


def _crawl():
    rec = {"type": "hidden", "content": "온라인 카지노 바로가기", "selector": "#content > div", "frame_path": [],
           "frame_url": START, "hidden_reasons": ["display:none"], "links": ["http://casino.invalid/"]}
    search = {"type": "text", "content": "'카지노 규제' 검색 결과", "selector": "#result > p", "frame_path": [],
              "frame_url": START}
    pages = [
        {"url": START, "final_url": START, "elements": [rec]},
        {"url": START + "search.do?q=%EC%B9%B4%EC%A7%80%EB%85%B8+%EA%B7%9C%EC%A0%9C", "final_url": "",
         "elements": [search]},
    ]
    return {"meta": {"start_url": START, "config": {"include_subdomains": True}}, "pages": pages}


@pytest.fixture
def app():
    from ad_sentinel.gui.app import App

    try:
        window = App()
    except tk.TclError:
        pytest.skip("화면(디스플레이)이 없는 환경")
    yield window
    window.destroy()


def test_results_table_and_detail(app):
    crawl = _crawl()
    app._show_report(crawl, detect(crawl))
    rows = [app.table.item(k)["values"] for k in app.table.get_children()]
    assert [r[:2] for r in rows] == [["불법광고 의심", "숨김 광고"], ["검토 필요", "악용 가능 지점"]]
    assert app.table.selection() == ()
    assert "결과를 클릭하면 상세 내용이 표시됩니다" in app.detail.get("1.0", "end")

    app.table.selection_set(app.table.get_children()[1])
    app.update()
    detail = app.detail.get("1.0", "end")
    assert "입력값을 그대로 출력하지 않도록 조치" in detail
    assert "q=카지노 규제" in detail
    assert "search.do?q=카지노 규제" in detail


def test_zero_findings_shows_summary_and_unchecked(app):
    import json
    from pathlib import Path

    crawl = json.loads((Path(__file__).parent / "fixtures" / "mois_sample.json").read_text(encoding="utf-8"))
    app._show_report(crawl, detect(crawl))
    detail = app.detail.get("1.0", "end")
    assert "발견된 불법광고가 없습니다" in detail and "점검한 페이지: 10개" in detail
    assert "점검하지 못한 영역: 1곳" in detail
    assert app.unchecked_button.winfo_manager() == "pack"
    assert app.unchecked_text.get() == "⚠ 점검하지 못한 영역 1곳"
    app._show_unchecked()
    detail = app.detail.get("1.0", "end")
    assert "https://www.korea.kr/etc/news_widget.do" in detail and "신뢰 도메인" in detail


def test_simple_and_detail_log(app):
    from ad_sentinel.gui.app import _page_message

    page = {"url": START, "title": "테스트 기관", "error": None}
    assert _page_message(3, page, 0, 0) == "3번째 페이지 점검 완료: 테스트 기관 (이상 없음)"
    assert _page_message(1, page, 2, 1) == "1번째 페이지 점검 완료: 테스트 기관 (의심 2건, 점검하지 못한 영역 1곳)"
    app._say("쉬운 문구")
    app._add_log("  프레임 1/1 메인 0.01s", simple=False)
    assert "쉬운 문구" in app.log.get("1.0", "end") and "프레임" not in app.log.get("1.0", "end")
    app.show_detail_log.set(True)
    app._render_log()
    assert "프레임" in app.log.get("1.0", "end")


def test_mode_switch_and_validation(app, monkeypatch):
    warnings = []
    monkeypatch.setattr("ad_sentinel.gui.app.messagebox.showwarning", lambda *a: warnings.append(a))
    app.mode.set("list")
    app._on_mode_change()
    assert app._make_config() is None and "목록" in warnings[-1][0]

    app.mode.set("site")
    app._on_mode_change()
    app.start_url.set("www.example.go.kr")
    config = app._make_config()
    assert config.start_url == "https://www.example.go.kr" and config.respect_robots is True


def test_own_site_checkbox_asks_once(app, monkeypatch):
    asked = []
    monkeypatch.setattr("ad_sentinel.gui.app.messagebox.askyesno", lambda *a, **k: asked.append(a) or False)
    app.own_site.set(True)
    app._on_own_site()
    assert len(asked) == 1 and "권한" in asked[0][1]
    assert app.own_site.get() is False


def test_gate_option_and_notices(app):
    app.start_url.set("https://www.example.go.kr/")
    assert app._make_config().enter_gate is True
    app.enter_gate.set(False)
    assert app._make_config().enter_gate is False

    app._handle_event(("notice", "입장 버튼('입장하기') 클릭 후 점검 계속 (링크 0개 → 3개)"))
    assert "입장 버튼('입장하기') 클릭 후 점검 계속" in app.log.get("1.0", "end")

    crawl = _crawl()
    report = detect(crawl)
    report["meta"]["notes"] = ["발견한 링크가 적어 2페이지만 점검했습니다. 입장 버튼이 있는 사이트라면 입장 후 주소를 시작 주소로 넣어보세요."]
    app._show_report(crawl, report)
    assert "발견한 링크가 적어 2페이지만" in app.detail.get("1.0", "end")
