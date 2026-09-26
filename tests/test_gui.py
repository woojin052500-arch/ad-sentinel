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

    app.table.selection_set(app.table.get_children()[1])
    app.update()
    detail = app.detail.get("1.0", "end")
    assert "입력값을 그대로 출력하지 않도록 조치" in detail
    assert "q=카지노 규제" in detail
    assert "search.do?q=카지노 규제" in detail


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
