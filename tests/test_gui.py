import json
from pathlib import Path

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

    crawl = json.loads((Path(__file__).parent / "fixtures" / "mois_sample.json").read_text(encoding="utf-8"))
    app._show_report(crawl, detect(crawl))
    detail = app.detail.get("1.0", "end")
    assert "발견된 불법광고가 없습니다" in detail and "점검한 페이지: 10개" in detail
    assert "점검하지 못한 영역: 1곳" in detail
    assert app.unchecked_button.winfo_manager() == "grid"
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
    app._flush_log()
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
    config = app._make_config()
    assert config.headless is True and config.screenshot_dir == ""
    app.show_browser.set(True)
    app.show_detail_log.set(True)
    config = app._make_config()
    assert config.headless is False and Path(config.screenshot_dir).name == "screenshots"
    app.show_browser.set(False)
    app.show_detail_log.set(False)

    app._handle_event(("notice", "입장 버튼('입장하기') 클릭 후 점검 계속 (링크 0개 → 3개)"))
    app._flush_log()
    assert "입장 버튼('입장하기') 클릭 후 점검 계속" in app.log.get("1.0", "end")

    crawl = _crawl()
    report = detect(crawl)
    report["meta"]["notes"] = ["발견한 링크가 적어 2페이지만 점검했습니다. 입장 버튼이 있는 사이트라면 입장 후 주소를 시작 주소로 넣어보세요."]
    app._show_report(crawl, report)
    assert "발견한 링크가 적어 2페이지만" in app.detail.get("1.0", "end")


def test_help_icons_tooltips_and_quick_start(app):
    from ad_sentinel.help_texts import SETTINGS

    assert set(SETTINGS) <= set(app.help_icons)
    assert "unchecked" in app.help_icons
    assert app.help_icons["page_timeout"].text().startswith("무엇인가요: 한 페이지를")
    assert "3단계 사용법" in app.detail.get("1.0", "end") and "결과 확인" in app.detail.get("1.0", "end")

    app.max_pages.set(100)
    app.update_idletasks()
    assert app.estimate.get() == "(예상 약 8분)"

    icon = app.help_icons["delay"]
    icon.tooltip.show(("요청 간격", icon.text()))
    assert icon.tooltip.window is not None
    icon.tooltip.hide()
    assert icon.tooltip.window is None

    app.update()
    heading_x = app.table.bbox(app.table.get_children()[0])[0] if app.table.get_children() else 10

    class Event:
        x, y = heading_x + 5, 5

    title, body = app._heading_help(Event())
    assert title == "판정" and "불법광고 의심" in body
    assert app.table.heading("score")["text"] == "점수 ?"

    app._show_help_window()
    assert "페이지당 제한 시간" in app.help_text.get("1.0", "end") and "점검하지 못한 영역" in app.help_text.get("1.0", "end")
    app.help_window.destroy()


def test_unchecked_explanation(app):
    import json

    crawl = json.loads((Path(__file__).parent / "fixtures" / "mois_sample.json").read_text(encoding="utf-8"))
    report = detect(crawl)
    app._show_report(crawl, report)
    assert report.get("unchecked")
    assert app.unchecked_help.winfo_manager() == "grid"
    app._show_unchecked()
    text = app.detail.get("1.0", "end")
    assert "왜 확인해야 하나요" in text and "숨겨진 iframe" in text


def _visible_controls(widget):
    for child in widget.winfo_children():
        if child.winfo_ismapped() and child.winfo_class() in ("TButton", "TCheckbutton", "TRadiobutton", "Canvas"):
            yield child
        yield from _visible_controls(child)


@pytest.mark.parametrize("mode", ["site", "list"])
def test_all_controls_fit_at_content_width(app, mode):
    app.mode.set(mode)
    app._on_mode_change()
    app.show_advanced.set(True)
    app._toggle_advanced()
    crawl = json.loads((Path(__file__).parent / "fixtures" / "mois_sample.json").read_text(encoding="utf-8"))
    app._show_report(crawl, detect(crawl))
    app.update()
    need = app.content.winfo_reqwidth()
    app.geometry(f"{need}x{app.minsize()[1] + 200}")
    app.update()
    assert not app.hbar.winfo_ismapped()
    right = app.winfo_rootx() + app.winfo_width()
    controls = [c for c in _visible_controls(app) if c is not app.viewport]
    assert len(controls) > 20
    clipped = [(c.winfo_class(), c.cget("text") if c.winfo_class() != "Canvas" else "?")
               for c in controls if c.winfo_rootx() + c.winfo_width() > right + 1 or c.winfo_width() < c.winfo_reqwidth()]
    assert clipped == []


@pytest.mark.parametrize("width", [700, "min"])
def test_narrow_window_scrolls_instead_of_clipping(app, width):
    crawl = json.loads((Path(__file__).parent / "fixtures" / "mois_sample.json").read_text(encoding="utf-8"))
    app._show_report(crawl, detect(crawl))
    width = app.minsize()[0] if width == "min" else width
    assert app.minsize()[0] <= width <= 700
    app.geometry(f"{width}x700")
    app.update()
    need = app.content.winfo_reqwidth()
    assert app.winfo_width() == width and need > width
    assert app.hbar.winfo_ismapped()
    assert float(app.viewport.cget("scrollregion").split()[2]) == need
    left = app.winfo_rootx()
    assert app.start_button.winfo_rootx() >= left
    html_button = next(c for c in _visible_controls(app) if c.winfo_class() == "TButton"
                       and c.cget("text") == "HTML 보고서로 저장")
    app.viewport.xview_moveto(1.0)
    app.update()
    assert html_button.winfo_rootx() + html_button.winfo_width() <= left + app.winfo_width() + 1
    app.geometry(f"{need + 40}x700")
    app.update()
    assert not app.hbar.winfo_ismapped() and app.start_button.winfo_rootx() >= left


def test_resize_is_debounced(app, monkeypatch):
    done = []
    monkeypatch.setattr(app, "_on_resize_done", lambda: done.append(app.winfo_width()))
    app.update()
    w, h = app.winfo_width(), app.winfo_height()
    for step in range(5):
        app.geometry(f"{w - 10 * (step + 1)}x{h}")
        app.update()
    assert app._resize_job is not None and done == []
    app.after(400, app.quit)
    app.mainloop()
    assert len(done) == 1


def test_icons_are_loaded(app):
    assert app.icon_problems == []
    assert len(app._icon_images) == 6 and app._icon_images[0].width() == 256


def test_cloaking_option_and_detail(app):
    from ad_sentinel.config import CLOAKING_MODES

    app.start_url.set("https://www.example.go.kr/")
    assert app._make_config().cloaking_check == "off"
    app.cloaking_label.set(CLOAKING_MODES["suspect"])
    assert app._make_config().cloaking_check == "suspect"
    app.cloaking_label.set(CLOAKING_MODES["off"])

    def snap(key, label, only_in, text, links=()):
        return {"key": key, "label": label, "only_in": only_in, "title": "복지 안내", "text": text,
                "links": list(links), "redirects": [], "hidden": [], "error": None}

    profiles = [snap("pc", "일반 PC", "", "기초연금 신청 안내"),
                snap("googlebot", "구글봇", "구글봇으로 볼 때만 나타남", "바카라 사이트 추천 카지노 첫충",
                     ["https://win777-casino.invalid/"])]
    page = {"url": START, "final_url": START, "elements": [], "frames": [], "cloaking": {"profiles": profiles}}
    crawl = {"meta": {"start_url": START, "config": {"include_subdomains": True}}, "pages": [page]}
    report = detect(crawl)
    app._show_report(crawl, report)
    first = app.table.get_children()[0]
    assert app.table.item(first)["values"][1] == "클로킹(구글봇)"
    app.table.selection_set(first)
    app._on_select()
    text = app.detail.get("1.0", "end")
    assert "클로킹 비교 (구글봇)" in text and "구글봇으로 볼 때만 나타남" in text and "win777-casino.invalid" in text


def test_log_updates_are_batched_and_trimmed(app, monkeypatch):
    import ad_sentinel.gui.app as gui

    monkeypatch.setattr(gui, "MAX_LOG_LINES", 50)
    for i in range(120):
        app._say(f"줄 {i}")
    assert "줄 0" not in app.log.get("1.0", "end")
    assert len(app.pending_log) == 120 and app.log_job
    app._flush_log()
    text = app.log.get("1.0", "end")
    assert "줄 119" in text and "줄 60" not in text
    assert int(app.log.index("end-1c").split(".")[0]) - 1 <= 50


def test_progress_events_are_coalesced(app, monkeypatch):
    handled = []
    original = app._handle_event
    monkeypatch.setattr(app, "_handle_event", lambda e: (handled.append(e[0]), original(e)))
    for i in range(30):
        app.events.put(("progress", i, 30, f"https://www.example.go.kr/{i}"))
    app.events.put(("notice", "안내"))
    app._poll_events()
    assert handled.count("progress") == 1 and "notice" in handled
    assert app.progress["value"] == 29


def test_light_ui_toggle_is_saved(app, monkeypatch, tmp_path):
    import ad_sentinel.gui.app as gui

    monkeypatch.setattr(gui, "data_dir", lambda: tmp_path)
    style = ttk_style(app)
    app.light_ui.set(True)
    app._toggle_light_ui()
    assert style.theme_use() == gui.light_theme_name(style)
    assert json.loads((tmp_path / gui.UI_SETTINGS_FILE).read_text(encoding="utf-8")) == {"light_ui": True}
    assert gui.load_ui_settings() == {"light_ui": True}
    app.light_ui.set(False)
    app._toggle_light_ui()
    assert style.theme_use() != gui.light_theme_name(style)
    assert "light_ui" in app.help_icons


def ttk_style(app):
    from tkinter import ttk

    return ttk.Style(app)


def test_pattern_column_fits_longest_label(app):
    cell_font = gui_font(app)
    width = app.table.column("pattern", "width")
    for label in ("클로킹(구글 경유)", "URL 파라미터 반사", "검색어 목록 오염"):
        assert cell_font.measure(label) + 16 <= width


def gui_font(app):
    from tkinter import font as tkfont

    from ad_sentinel.gui.app import _font_of

    return _font_of("Treeview") or tkfont.nametofont("TkDefaultFont")


def test_browser_error_dialog_and_error_log(app, monkeypatch, tmp_path):
    import ad_sentinel.gui.app as gui
    from ad_sentinel.crawler.browser import BROWSER_ERROR_TITLE

    shown = []
    monkeypatch.setattr(gui.messagebox, "showerror", lambda title, message, **kw: shown.append((title, message)))
    app._handle_event(("error", "점검에 쓰는 브라우저(Microsoft Edge)를 실행하지 못했습니다.\n\n자세한 오류", BROWSER_ERROR_TITLE))
    assert shown[-1][0] == "브라우저를 실행하지 못했습니다"
    app._flush_log()
    assert "브라우저(Microsoft Edge)를 실행하지 못했습니다" in app.log.get("1.0", "end")

    monkeypatch.setattr(gui, "data_dir", lambda: tmp_path)
    try:
        raise ValueError("테스트 오류")
    except ValueError:
        path = gui.write_error_log("시작 오류")
    text = path.read_text(encoding="utf-8")
    assert path == tmp_path / "error.log" and "시작 오류" in text and "ValueError: 테스트 오류" in text
