import json
import logging
import queue
import threading
import time
import tkinter as tk
import traceback
import webbrowser
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, font, messagebox, ttk

from ad_sentinel import __version__
from ad_sentinel.config import CLOAKING_MODES, CLOAKING_OFF, OWN_SITE_LABEL, ROBOTS_IGNORE_WARNING, CrawlConfig
from ad_sentinel.crawler import Crawler
from ad_sentinel.crawler.browser import BROWSER_ERROR_TITLE, BrowserLaunchError
from ad_sentinel.detector import detect
from ad_sentinel.detector.domains import DEFAULT_WHITELIST, read_user_whitelist, save_user_whitelist
from ad_sentinel.gui import winicon
from ad_sentinel.gui.tooltip import HelpIcon, Tooltip, help_content
from ad_sentinel.help_texts import (COLUMNS, QUICK_START, QUICK_START_FOOTER, QUICK_START_TITLE, SETTINGS,
                                    UNCHECKED, estimate_text, quick_start_text)
from ad_sentinel.paths import asset_path, data_dir, output_dir
from ad_sentinel.report import (display_url, export_csv, export_html, export_json, location_text,
                                reflected_text, stats_lines)
from ad_sentinel.storage import load_json, save_json
from ad_sentinel.url_list import load_url_list

APP_TITLE = "AD Sentinel - 공공 웹사이트 불법광고 점검"
SITE, LIST = "site", "list"
LEVEL_COLORS = {"high": "#fde2e1", "suspect": "#fff1d6"}
LIST_FILE_TYPES = [("주소 목록 파일", "*.txt *.csv *.tsv *.zip"), ("모든 파일", "*.*")]
KOREAN_FONTS = ("Malgun Gothic", "맑은 고딕", "Noto Sans CJK KR", "Noto Sans KR", "NanumGothic", "WenQuanYi Zen Hei")
MAX_LOG_LINES = 3000
HINT_COLOR = "#6b7280"
RESIZE_SETTLE_MS = 150
POLL_MS = 200
MIN_WIDTH, MIN_HEIGHT = 560, 560
UI_SETTINGS_FILE = "ui_settings.json"
ICON_PHOTO_SIZES = (256, 64, 48, 32, 24, 16)

log = logging.getLogger(__name__)


class QueueLogHandler(logging.Handler):
    def __init__(self, events: queue.Queue):
        super().__init__(logging.INFO)
        self.events = events
        self.setFormatter(logging.Formatter("%(asctime)s %(message)s", "%H:%M:%S"))

    def emit(self, record):
        if record.name.startswith("ad_sentinel.notice"):
            self.events.put(("notice", record.getMessage()))
        else:
            self.events.put(("log", self.format(record)))


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"{APP_TITLE} (v{__version__})")
        self.scale = max(1.0, self.winfo_fpixels("1i") / 96.0)
        self.ui_settings = load_ui_settings()
        self.light_ui = tk.BooleanVar(value=bool(self.ui_settings.get("light_ui", True)))
        _apply_theme(self, self.scale, self.light_ui.get())
        self.configure(background=_theme_background(self))
        self.icon_problems = _set_icon(self)
        ttk.Style(self).configure("TLabelframe.Label", font=_bold_font())
        self.pending_log: list[str] = []
        self.log_job: str | None = None

        self.events: queue.Queue = queue.Queue()
        self.stop_event = threading.Event()
        self.worker: threading.Thread | None = None
        self.crawl_result: dict | None = None
        self.report: dict | None = None
        self.url_list: list[str] = []
        self.simple_log: list[str] = []
        self.detail_log: list[str] = []
        self.open_target = ""

        self.mode = tk.StringVar(value=SITE)
        self.start_url = tk.StringVar()
        self.max_pages = tk.IntVar(value=30)
        self.max_depth = tk.IntVar(value=3)
        self.own_site = tk.BooleanVar(value=False)
        self.enter_gate = tk.BooleanVar(value=True)
        self.sitemap_url = tk.StringVar()
        self.delay_sec = tk.DoubleVar(value=CrawlConfig.delay_sec)
        self.page_timeout = tk.IntVar(value=int(CrawlConfig.page_total_timeout_sec))
        self.show_advanced = tk.BooleanVar(value=False)
        self.show_browser = tk.BooleanVar(value=False)
        self.cloaking_label = tk.StringVar(value=CLOAKING_MODES[CLOAKING_OFF])
        self.run_started = 0.0
        self.show_detail_log = tk.BooleanVar(value=False)
        self.list_info = tk.StringVar(value="불러온 목록 없음")
        self.status = tk.StringVar(value="점검할 사이트 주소를 입력하고 [점검 시작]을 누르세요.")
        self.count_text = tk.StringVar(value="")
        self.summary = tk.StringVar(value="")
        self.unchecked_text = tk.StringVar(value="")
        self.estimate = tk.StringVar(value="")
        self.help_icons: dict[str, HelpIcon] = {}
        self.wrap_labels: list[ttk.Label] = []

        self._build()
        self._fit_window(1280, 800, MIN_WIDTH, MIN_HEIGHT)
        self._resize_job: str | None = None
        self._last_size = (0, 0)
        self.bind("<Configure>", self._on_configure, add="+")
        self._on_mode_change()
        self.max_pages.trace_add("write", lambda *_: self._update_estimate())
        self._update_estimate()
        self._show_quick_start()

        self.log_handler = QueueLogHandler(self.events)
        logging.getLogger("ad_sentinel").addHandler(self.log_handler)
        logging.getLogger("ad_sentinel").setLevel(logging.INFO)
        for problem in self.icon_problems:
            log.info("아이콘 설정 실패: %s", problem)
        self.after(200, self._apply_native_icon)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(100, self._poll_events)

    def px(self, value: float) -> int:
        return int(value * self.scale)

    def _fit_window(self, width: int, height: int, min_width: int, min_height: int):
        self.update_idletasks()
        screen_w, screen_h = self.winfo_screenwidth(), self.winfo_screenheight()
        need_w = self.content.winfo_reqwidth()
        w = min(max(self.px(width), need_w), screen_w - self.px(40))
        h = min(self.px(height), screen_h - self.px(80))
        self.geometry(f"{w}x{h}+{max(0, (screen_w - w) // 2)}+{max(0, (screen_h - h) // 3)}")
        self.minsize(min(self.px(min_width), w), min(self.px(min_height), h))

    def _layout_viewport(self, width: int | None = None, height: int | None = None):
        if self._in_layout:
            return
        self._in_layout = True
        try:
            self.update_idletasks()
        finally:
            self._in_layout = False
        width = self.viewport.winfo_width() if width is None else width
        height = self.viewport.winfo_height() if height is None else height
        need = self.content.winfo_reqwidth()
        full = max(width, need)
        self.viewport.itemconfigure(self.content_item, width=full, height=height)
        self.viewport.configure(scrollregion=(0, 0, full, height))
        if need > width + 1:
            if not self.hbar.winfo_ismapped():
                self.hbar.pack(side="bottom", fill="x", before=self.viewport)
        elif self.hbar.winfo_ismapped():
            self.hbar.pack_forget()
        if need <= width:
            self.viewport.xview_moveto(0)
        if need != self._laid_out_need:
            self._laid_out_need = need
            self.after_idle(self._layout_viewport)

    def _relayout(self):
        self.after_idle(self._layout_viewport)

    def report_callback_exception(self, exc, value, tb):
        logging.getLogger("ad_sentinel").error("화면 처리 오류", exc_info=(exc, value, tb))
        path = data_dir() / "error.log"
        try:
            with open(path, "a", encoding="utf-8") as f:
                f.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] v{__version__} 화면 처리 오류\n")
                f.write("".join(traceback.format_exception(exc, value, tb)) + "\n")
        except OSError:
            pass
        messagebox.showerror("오류", f"화면 처리 중 오류가 났습니다: {value}\n\n오류 기록: {path}", parent=self)

    def _apply_native_icon(self):
        problem = _set_native_icon(self)
        if problem:
            log.info("아이콘 설정 실패: %s", problem)

    def _on_configure(self, event):
        if event.widget is not self or (event.width, event.height) == self._last_size:
            return
        self._last_size = (event.width, event.height)
        if self._resize_job:
            self.after_cancel(self._resize_job)
        else:
            self._hide_tooltips()
        self._resize_job = self.after(RESIZE_SETTLE_MS, self._on_resize_done)

    def _on_resize_done(self):
        self._resize_job = None
        width = self.winfo_width()
        for label in self.wrap_labels:
            label.configure(wraplength=max(self.px(300), width - self.px(80)))

    def _hide_tooltips(self):
        self.table_tooltip.hide()
        for icon in self.help_icons.values():
            icon.tooltip.hide()

    def _build(self):
        pad = self.px(6)
        self._laid_out_need = 0
        self._in_layout = False
        self.viewport = tk.Canvas(self, highlightthickness=0, borderwidth=0, background=_theme_background(self))
        self.hbar = ttk.Scrollbar(self, orient="horizontal", command=self.viewport.xview)
        self.viewport.configure(xscrollcommand=self.hbar.set)
        self.viewport.pack(side="top", fill="both", expand=True)
        root = ttk.Frame(self.viewport, padding=self.px(10))
        self.content = root
        self.content_item = self.viewport.create_window(0, 0, window=root, anchor="nw")
        self.viewport.bind("<Configure>", lambda e: self._layout_viewport(e.width, e.height))

        mode_box = ttk.LabelFrame(root, text="1. 점검 방식", padding=pad)
        mode_box.pack(fill="x")
        ttk.Radiobutton(mode_box, text="사이트 점검 - 시작 주소에서 링크를 따라가며 하위 페이지를 점검",
                        variable=self.mode, value=SITE, command=self._on_mode_change).grid(row=0, column=0, sticky="w",
                                                                                           padx=(0, pad))
        ttk.Radiobutton(mode_box, text="URL 목록 점검 - 주소 목록 파일(서치 콘솔에서 내보낸 파일 등)에 있는 주소만 점검",
                        variable=self.mode, value=LIST, command=self._on_mode_change).grid(row=1, column=0, sticky="w")
        intro = ttk.Frame(mode_box)
        intro.grid(row=0, column=1, rowspan=2, sticky="e")
        intro_top = ttk.Frame(intro)
        intro_top.pack(anchor="e")
        ttk.Label(intro_top, text="처음 사용하시나요?", font=_bold_font()).pack(side="left", padx=(0, pad))
        ttk.Button(intro_top, text="3단계 사용법", command=self._show_quick_start_dialog).pack(side="left")
        ttk.Button(intro_top, text="설정·결과 설명", command=self._show_help_window).pack(side="left", padx=(pad, 0))
        ttk.Label(intro, text="설정 옆 ? 에 마우스를 올리면 설명이 나옵니다.", foreground=HINT_COLOR).pack(anchor="e")
        mode_box.columnconfigure(0, weight=1)

        target = ttk.LabelFrame(root, text="2. 점검 대상", padding=pad)
        target.pack(fill="x", pady=(pad, 0))

        self.site_frame = ttk.Frame(target)
        ttk.Label(self.site_frame, text="시작 주소").grid(row=0, column=0, sticky="w", padx=(0, pad))
        url_entry = ttk.Entry(self.site_frame, textvariable=self.start_url)
        url_entry.grid(row=0, column=1, sticky="we")
        url_entry.bind("<Return>", lambda e: self._start())
        ttk.Label(self.site_frame, text="예: https://www.example.go.kr", foreground=HINT_COLOR).grid(
            row=1, column=1, sticky="w")
        options = ttk.Frame(self.site_frame)
        options.grid(row=2, column=0, columnspan=2, sticky="w", pady=(pad, 0))
        ttk.Label(options, text="최대 페이지 수").pack(side="left")
        self._help(options, "max_pages").pack(side="left", padx=(pad // 2, 0))
        ttk.Spinbox(options, from_=1, to=5000, textvariable=self.max_pages, width=6).pack(side="left", padx=pad)
        ttk.Label(options, textvariable=self.estimate, foreground=HINT_COLOR).pack(side="left")
        ttk.Label(options, text="링크 깊이").pack(side="left", padx=(pad * 3, 0))
        self._help(options, "max_depth").pack(side="left", padx=(pad // 2, 0))
        ttk.Spinbox(options, from_=0, to=10, textvariable=self.max_depth, width=4).pack(side="left", padx=pad)
        ttk.Label(options, text="(첫 화면 → 게시판 → 게시글 = 2단계)", foreground=HINT_COLOR).pack(side="left")
        gate_row = ttk.Frame(self.site_frame)
        gate_row.grid(row=3, column=0, columnspan=2, sticky="w", pady=(pad, 0))
        ttk.Checkbutton(gate_row, variable=self.enter_gate,
                        text="첫 화면의 '입장' 버튼 자동 클릭 (로그인·가입·결제·삭제·신고 버튼은 누르지 않음)").pack(side="left")
        self._help(gate_row, "enter_gate").pack(side="left", padx=(pad // 2, 0))
        sitemap_label = ttk.Frame(self.site_frame)
        sitemap_label.grid(row=4, column=0, sticky="w", padx=(0, pad), pady=(pad, 0))
        ttk.Label(sitemap_label, text="sitemap 또는 RSS 주소 (선택)").pack(side="left")
        self._help(sitemap_label, "sitemap").pack(side="left", padx=(pad // 2, 0))
        ttk.Entry(self.site_frame, textvariable=self.sitemap_url).grid(row=4, column=1, sticky="we", pady=(pad, 0))
        sitemap_hint = ttk.Label(self.site_frame, foreground=HINT_COLOR, justify="left",
                                 text="예: https://www.example.go.kr/all/sitemap.xml · 비워 두면 자동으로 찾습니다.")
        sitemap_hint.grid(row=5, column=1, sticky="w")
        self.wrap_labels.append(sitemap_hint)
        self.site_frame.columnconfigure(1, weight=1)

        self.list_frame = ttk.Frame(target)
        ttk.Button(self.list_frame, text="목록 파일 불러오기...", command=self._load_list).grid(
            row=0, column=0, sticky="w")
        ttk.Label(self.list_frame, textvariable=self.list_info).grid(row=0, column=1, sticky="w", padx=pad)
        list_hint = ttk.Label(self.list_frame, foreground=HINT_COLOR, justify="left",
                              text="txt(한 줄에 주소 하나), CSV(첫 번째 열), 구글 서치 콘솔 '내보내기' 파일(csv 또는 zip)을 읽습니다. "
                                   "목록의 주소만 점검하고 링크는 따라가지 않습니다.", wraplength=self.px(900))
        list_hint.grid(row=1, column=0, columnspan=2, sticky="w", pady=(pad, 0))
        self.wrap_labels.append(list_hint)
        self.list_frame.columnconfigure(1, weight=1)

        bottom = ttk.Frame(target)
        bottom.pack(fill="x", side="bottom", pady=(pad, 0))
        bottom_row = ttk.Frame(bottom)
        bottom_row.pack(fill="x")
        ttk.Checkbutton(bottom_row, text=OWN_SITE_LABEL, variable=self.own_site,
                        command=self._on_own_site).pack(side="left")
        self._help(bottom_row, "own_site").pack(side="left", padx=(pad // 2, 0))
        ttk.Checkbutton(bottom_row, text="고급 설정", variable=self.show_advanced,
                        command=self._toggle_advanced).pack(side="left", padx=(pad * 4, pad))
        self.advanced_frame = ttk.Frame(bottom)
        adv = ttk.Frame(self.advanced_frame)
        adv.pack(fill="x")
        ttk.Label(adv, text="요청 간격").pack(side="left")
        self._help(adv, "delay").pack(side="left", padx=(pad // 2, 0))
        ttk.Spinbox(adv, from_=0, to=30, increment=0.5, textvariable=self.delay_sec,
                    width=5).pack(side="left", padx=pad)
        ttk.Label(adv, text="초 (차단되면 자동으로 늘림)").pack(side="left")
        ttk.Label(adv, text="페이지당 제한 시간").pack(side="left", padx=(pad * 4, 0))
        self._help(adv, "page_timeout").pack(side="left", padx=(pad // 2, 0))
        ttk.Spinbox(adv, from_=10, to=600, increment=10, textvariable=self.page_timeout,
                    width=5).pack(side="left", padx=pad)
        ttk.Label(adv, text="초").pack(side="left")
        ttk.Checkbutton(adv, text="브라우저 창 보이기(진단용)",
                        variable=self.show_browser).pack(side="left", padx=(pad * 4, 0))
        self._help(adv, "show_browser").pack(side="left", padx=(pad // 2, 0))
        adv2 = ttk.Frame(self.advanced_frame)
        adv2.pack(fill="x", pady=(pad, 0))
        ttk.Label(adv2, text="클로킹 검사").pack(side="left")
        self._help(adv2, "cloaking").pack(side="left", padx=(pad // 2, 0))
        self.cloaking_box = ttk.Combobox(adv2, state="readonly", width=22, textvariable=self.cloaking_label,
                                         values=list(CLOAKING_MODES.values()))
        self.cloaking_box.pack(side="left", padx=pad)
        ttk.Label(adv2, foreground=HINT_COLOR,
                  text="(구글봇·구글 검색 경유·모바일로도 열어 비교)").pack(side="left")
        ttk.Checkbutton(adv2, text="가벼운 화면(Windows 기본 테마)", variable=self.light_ui,
                        command=self._toggle_light_ui).pack(side="left", padx=(pad * 4, 0))
        self._help(adv2, "light_ui").pack(side="left", padx=(pad // 2, 0))

        buttons = ttk.Frame(root)
        buttons.pack(fill="x", pady=pad)
        self.start_button = ttk.Button(buttons, text="▶  점검 시작", command=self._start, style="Accent.TButton")
        self.start_button.pack(side="left")
        self.stop_button = ttk.Button(buttons, text="■  중지", command=self._stop, state="disabled")
        self.stop_button.pack(side="left", padx=pad)
        self.load_button = ttk.Button(buttons, text="저장된 점검 결과 불러오기...", command=self._load_result)
        self.load_button.pack(side="right")
        self.whitelist_button = ttk.Button(buttons, text="신뢰 도메인 관리...", command=self._edit_whitelist)
        self.whitelist_button.pack(side="right", padx=pad)

        progress = ttk.LabelFrame(root, text="3. 진행 상황", padding=pad)
        progress.pack(fill="x")
        top = ttk.Frame(progress)
        top.pack(fill="x")
        ttk.Label(top, textvariable=self.status).pack(side="left")
        self._help(top, "detail_log").pack(side="right", padx=(pad // 2, 0))
        ttk.Checkbutton(top, text="상세 로그 보기", variable=self.show_detail_log,
                        command=self._render_log).pack(side="right")
        ttk.Label(top, textvariable=self.count_text).pack(side="right", padx=self.px(12))
        self.progress = ttk.Progressbar(progress, mode="determinate")
        self.progress.pack(fill="x", pady=pad)
        self.log = self._text_box(progress, height=4, wrap="none")

        results = ttk.LabelFrame(root, text="4. 점검 결과", padding=pad)
        results.pack(fill="both", expand=True, pady=(pad, 0))
        header = ttk.Frame(results)
        header.pack(fill="x")
        ttk.Label(header, textvariable=self.summary, font=_bold_font()).grid(row=0, column=0, sticky="w")
        self.unchecked_button = ttk.Button(header, textvariable=self.unchecked_text, command=self._show_unchecked)
        self.unchecked_help = self._help(header, "unchecked")
        for column, (text, command) in enumerate([("JSON으로 저장", self._export_json), ("CSV로 저장", self._export_csv),
                                                  ("HTML 보고서로 저장", self._export_html)], 3):
            ttk.Button(header, text=text, command=command).grid(row=0, column=column, padx=(pad, 0))
        header.columnconfigure(0, weight=1)

        panes = ttk.PanedWindow(results, orient="horizontal")
        panes.pack(fill="both", expand=True, pady=(pad, 0))
        panes.add(self._build_table(panes), weight=5)

        detail_frame = ttk.Frame(panes)
        self.detail = self._text_box(detail_frame, wrap="word", width=30)
        body = font.nametofont("TkTextFont")
        self.detail.tag_configure("title", font=(body.actual("family"), body.actual("size") + 1, "bold"))
        self.detail.tag_configure("label", font=(body.actual("family"), body.actual("size"), "bold"),
                                  spacing1=self.px(8))
        self.detail.tag_configure("advice", background="#eef6ff", lmargin1=self.px(4), lmargin2=self.px(4))
        self.detail.tag_configure("warn", background="#fff4e5", lmargin1=self.px(4), lmargin2=self.px(4))
        self.detail.tag_configure("hint", foreground=HINT_COLOR)
        detail_buttons = ttk.Frame(detail_frame)
        detail_buttons.pack(fill="x", pady=(pad, 0))
        ttk.Button(detail_buttons, text="페이지 열기", command=self._open_page).pack(side="left")
        ttk.Button(detail_buttons, text="위치(선택자) 복사", command=self._copy_selector).pack(side="left", padx=pad)
        panes.add(detail_frame, weight=3)

    def _build_table(self, parent) -> ttk.Frame:
        frame = ttk.Frame(parent)
        columns = [("level", "판정", "불법광고 의심"), ("pattern", "유형", "URL 파라미터 반사|클로킹(구글 경유)|검색어 목록 오염"),
                   ("category", "분류", "불법의약품"), ("score", "점수", "10"),
                   ("content", "내용", ""), ("pages", "페이지 수", "100개")]
        self.table = ttk.Treeview(frame, columns=[c for c, _, _ in columns], show="headings", selectmode="browse")
        heading_font = _font_of("Treeview.Heading") or font.nametofont("TkHeadingFont")
        cell_font = _font_of("Treeview") or font.nametofont("TkDefaultFont")
        for key, title, sample in columns:
            width = max([heading_font.measure(f"{title} ?")] + [cell_font.measure(t) for t in sample.split("|")])
            width += self.px(28)
            if key == "content":
                width = self.px(180)
            self.table.heading(key, text=f"{title} ?")
            self.table.column(key, width=width, minwidth=width if key != "content" else self.px(120),
                              anchor="w" if key == "content" else "center", stretch=key == "content")
        self._table_style()
        for level, color in LEVEL_COLORS.items():
            self.table.tag_configure(level, background=color)
        scroll = ttk.Scrollbar(frame, orient="vertical", command=self.table.yview)
        self.table.configure(yscrollcommand=scroll.set)
        self.table.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.table.bind("<<TreeviewSelect>>", self._on_select)
        self.table.bind("<Double-1>", lambda e: self._open_page())
        self.table_tooltip = Tooltip(self.table, self._heading_help, self.px(380))
        return frame

    def _table_style(self):
        cell_font = _font_of("Treeview") or font.nametofont("TkDefaultFont")
        ttk.Style(self).configure("Treeview", rowheight=int(cell_font.metrics("linespace") * 1.5))

    def _toggle_light_ui(self):
        _apply_theme(self, self.scale, self.light_ui.get())
        background = _theme_background(self)
        self.configure(background=background)
        self.viewport.configure(background=background)
        ttk.Style(self).configure("TLabelframe.Label", font=_bold_font())
        self._table_style()
        for icon in self.help_icons.values():
            icon.configure(background=background)
        self.ui_settings["light_ui"] = self.light_ui.get()
        save_ui_settings(self.ui_settings)
        self._relayout()

    def _heading_help(self, event) -> tuple[str, str] | None:
        if event is None or self.table.identify_region(event.x, event.y) != "heading":
            return None
        column = self.table.identify_column(event.x)
        try:
            key = self.table["columns"][int(column.lstrip("#")) - 1]
        except (ValueError, IndexError):
            return None
        return help_content(COLUMNS[key]) if key in COLUMNS else None

    def _help(self, parent, key: str) -> HelpIcon:
        item = UNCHECKED if key == "unchecked" else SETTINGS[key]
        icon = HelpIcon(parent, item, self.px(16), self.px(380))
        self.help_icons[key] = icon
        return icon

    def _update_estimate(self):
        try:
            pages = int(self.max_pages.get())
        except (tk.TclError, ValueError):
            self.estimate.set("")
            return
        self.estimate.set(f"(예상 {estimate_text(max(1, pages))})")

    def _show_quick_start(self):
        parts = [("title", QUICK_START_TITLE + "\n")]
        for i, (name, text) in enumerate(QUICK_START, 1):
            parts += [("label", f"{i}. {name}\n"), ("", text + "\n")]
        parts += [("label", "\n"), ("hint", QUICK_START_FOOTER + "\n점검을 시작하면 결과가 여기에 표시됩니다.\n")]
        self.open_target = ""
        self._set_detail(parts)

    def _show_quick_start_dialog(self):
        messagebox.showinfo(QUICK_START_TITLE, quick_start_text(), parent=self)

    def _show_help_window(self):
        window = tk.Toplevel(self)
        window.title("설정·결과 설명")
        window.transient(self)
        w = min(self.px(760), self.winfo_screenwidth() - self.px(40))
        h = min(self.px(640), self.winfo_screenheight() - self.px(80))
        window.geometry(f"{w}x{h}+{self.winfo_rootx() + self.px(40)}+{self.winfo_rooty() + self.px(40)}")
        frame = ttk.Frame(window, padding=self.px(10))
        frame.pack(fill="both", expand=True)
        ttk.Button(frame, text="닫기", command=window.destroy).pack(side="bottom", anchor="e", pady=(self.px(6), 0))
        text = self._text_box(frame, wrap="word")
        body = font.nametofont("TkTextFont")
        text.tag_configure("h1", font=(body.actual("family"), body.actual("size") + 2, "bold"), spacing1=self.px(10),
                           spacing3=self.px(4))
        text.tag_configure("h2", font=(body.actual("family"), body.actual("size"), "bold"), spacing1=self.px(8))
        text.tag_configure("hint", foreground=HINT_COLOR)
        parts = [("h1", QUICK_START_TITLE + "\n")]
        parts += [("", f"{i}. {name} - {desc}\n") for i, (name, desc) in enumerate(QUICK_START, 1)]
        for heading, items in (("설정 설명", SETTINGS.values()), ("결과 화면 설명", [*COLUMNS.values(), UNCHECKED])):
            parts.append(("h1", heading + "\n"))
            for item in items:
                parts.append(("h2", item.title + "\n"))
                for label, value in item.lines():
                    parts += [("hint", f"{label}: "), ("", value + "\n")]
        text.configure(state="normal")
        for tag, value in parts:
            text.insert("end", value, tag or ())
        text.configure(state="disabled")
        self.help_window, self.help_text = window, text

    def _text_box(self, parent, **options) -> tk.Text:
        frame = ttk.Frame(parent)
        frame.pack(fill="both", expand=True)
        text = tk.Text(frame, state="disabled", relief="flat", borderwidth=0, background="#ffffff",
                       highlightthickness=1, highlightbackground="#d0d4da", padx=self.px(6), pady=self.px(4),
                       font="TkTextFont", **options)
        scroll = ttk.Scrollbar(frame, orient="vertical", command=text.yview)
        text.configure(yscrollcommand=scroll.set)
        text.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        return text

    def _on_mode_change(self):
        if self.mode.get() == SITE:
            self.list_frame.pack_forget()
            self.site_frame.pack(fill="x")
        else:
            self.site_frame.pack_forget()
            self.list_frame.pack(fill="x")
        self._relayout()

    def _on_own_site(self):
        if self.own_site.get():
            ok = messagebox.askyesno("확인", ROBOTS_IGNORE_WARNING + "\n\n계속하시겠습니까?", icon="warning")
            self.own_site.set(ok)

    def _load_list(self):
        path = filedialog.askopenfilename(title="주소 목록 파일 선택", filetypes=LIST_FILE_TYPES)
        if not path:
            return
        try:
            urls = load_url_list(path)
        except Exception as e:
            messagebox.showerror("불러오기 실패", f"파일을 읽지 못했습니다.\n{e}")
            return
        if not urls:
            messagebox.showwarning("주소 없음", "파일에서 http:// 또는 https:// 로 시작하는 주소를 찾지 못했습니다.")
            return
        self.url_list = urls
        self.list_info.set(f"불러온 주소 {len(urls)}개 - {Path(path).name}")
        self._say(f"목록 파일 {Path(path).name}에서 주소 {len(urls)}개를 불러왔습니다.")

    def _toggle_advanced(self):
        if self.show_advanced.get():
            self.advanced_frame.pack(fill="x", pady=(self.px(6), 0))
        else:
            self.advanced_frame.pack_forget()
        self._relayout()

    def _make_config(self) -> CrawlConfig | None:
        try:
            delay, timeout = float(self.delay_sec.get()), float(self.page_timeout.get())
        except (tk.TclError, ValueError):
            messagebox.showwarning("입력 오류", "요청 간격과 페이지당 제한 시간은 숫자로 입력하세요.")
            return None
        common = dict(respect_robots=not self.own_site.get(), delay_sec=max(0.0, delay),
                      page_total_timeout_sec=max(10.0, timeout), enter_gate=self.enter_gate.get(),
                      headless=not self.show_browser.get(),
                      cloaking_check=next((k for k, v in CLOAKING_MODES.items() if v == self.cloaking_label.get()),
                                          CLOAKING_OFF),
                      screenshot_dir=str(output_dir() / "screenshots") if self.show_detail_log.get() else "")
        if self.mode.get() == LIST:
            if not self.url_list:
                messagebox.showwarning("목록 없음", "먼저 [목록 파일 불러오기]로 점검할 주소 목록을 불러오세요.")
                return None
            return CrawlConfig(url_list=list(self.url_list), **common)
        url = self.start_url.get().strip()
        if not url:
            messagebox.showwarning("주소 없음", "점검할 사이트의 시작 주소를 입력하세요.")
            return None
        if not url.lower().startswith(("http://", "https://")):
            url = "https://" + url
            self.start_url.set(url)
        try:
            max_pages, max_depth = int(self.max_pages.get()), int(self.max_depth.get())
        except (tk.TclError, ValueError):
            messagebox.showwarning("입력 오류", "최대 페이지 수와 링크 깊이는 숫자로 입력하세요.")
            return None
        sitemaps = [u.strip() for u in self.sitemap_url.get().replace(",", " ").split() if u.strip()]
        return CrawlConfig(start_url=url, max_pages=max(1, max_pages), max_depth=max(0, max_depth),
                           sitemap_urls=sitemaps, **common)

    def _start(self):
        if self.worker and self.worker.is_alive():
            return
        config = self._make_config()
        if not config:
            return
        self.stop_event = threading.Event()
        self._set_running(True)
        self._clear_results()
        total = len(config.url_list) if config.url_list else config.max_pages
        self.progress.configure(maximum=total, value=0)
        self.count_text.set(f"0 / {total}")
        self.status.set("브라우저를 준비하고 있습니다...")
        self.run_started = time.monotonic()
        if config.url_list:
            self._say(f"점검을 시작합니다. (URL 목록 점검 · 주소 {total}개)")
        else:
            self._say(f"점검을 시작합니다. (사이트 점검 · {config.start_url} · 최대 {total}페이지)")
        if not config.respect_robots:
            self._say("robots.txt 제한을 무시하고 점검합니다. (내가 관리하는 사이트 점검)")
        self.worker = threading.Thread(target=self._work, args=(config,), daemon=True)
        self.worker.start()

    def _work(self, config: CrawlConfig):
        seeds = config.url_list or [config.start_url]
        page_meta = {"start_url": seeds[0], "seed_urls": seeds,
                     "config": {"include_subdomains": config.include_subdomains}}

        def on_page(index: int, page: dict):
            try:
                mini = detect({"meta": page_meta, "pages": [page]})
                self.events.put(("page", index, page, mini["summary"]["findings"], mini["summary"]["unchecked"]))
            except Exception:
                self.events.put(("page", index, page, 0, 0))

        try:
            crawler = Crawler(config, on_progress=self._on_progress, stop_event=self.stop_event, on_page=on_page)
            crawl = crawler.run()
            crawl_path = save_json(crawl, prefix="crawl")
            report = detect(crawl)
            report_path = save_json(report, prefix="detect")
            self.events.put(("done", crawl, report, crawl_path, report_path))
        except BrowserLaunchError as e:
            self.events.put(("error", str(e), BROWSER_ERROR_TITLE))
        except Exception as e:
            logging.getLogger("ad_sentinel").exception("점검 중 오류")
            path = write_error_log("점검 중 오류")
            self.events.put(("error", f"{e}\n\n오류 기록: {path}", "오류"))

    def _on_progress(self, done: int, total: int, url: str):
        self.events.put(("progress", done, total, url))

    def _stop(self):
        self.stop_event.set()
        self.stop_button.configure(state="disabled")
        self.status.set("중지하는 중입니다. 지금 점검 중인 페이지를 마치고 멈춥니다...")
        self._say("중지를 요청했습니다. 지금 점검 중인 페이지를 마치고 멈춥니다.")

    def _poll_events(self):
        progress = None
        try:
            while True:
                event = self.events.get_nowait()
                if event[0] == "progress":
                    progress = event
                    continue
                if event[0] in ("done", "error") and progress:
                    self._handle_event(progress)
                    progress = None
                self._handle_event(event)
        except queue.Empty:
            pass
        if progress:
            self._handle_event(progress)
        self._flush_log()
        self.after(POLL_MS, self._poll_events)

    def _handle_event(self, event: tuple):
        kind = event[0]
        if kind == "log":
            self._add_log(event[1], simple=False)
        elif kind == "notice":
            self._say(event[1])
        elif kind == "progress":
            _, done, total, url = event
            self.progress.configure(maximum=max(total, 1), value=done)
            self.count_text.set(f"{done} / {total}" + _eta_text(done, total, time.monotonic() - self.run_started))
            if url and not self.stop_event.is_set():
                self.status.set(f"점검 중 ({done + 1}번째 페이지): {display_url(url)[:90]}")
        elif kind == "page":
            _, index, page, findings, unchecked = event
            self._say(_page_message(index, page, findings, unchecked))
        elif kind == "done":
            _, crawl, report, crawl_path, report_path = event
            self._set_running(False)
            stopped = crawl["meta"].get("stopped_by_user")
            checked = len(crawl["pages"])
            if not stopped:
                self.progress.configure(maximum=max(checked, 1))
            self.progress.configure(value=checked)
            self.count_text.set(f"{checked}페이지 점검")
            s = report["summary"]
            done_text = "사용자가 점검을 중지했습니다." if stopped else "점검을 마쳤습니다."
            self.status.set(f"{done_text} 페이지 {checked}개, 발견 {s['findings']}건")
            self._say(f"{done_text} 페이지 {checked}개 · 발견 {s['findings']}건 · 점검하지 못한 영역 {s['unchecked']}곳")
            self._add_log(f"점검 결과 저장: {crawl_path}", simple=False)
            self._add_log(f"탐지 결과 저장: {report_path}", simple=False)
            self._show_report(crawl, report)
        elif kind == "error":
            self._set_running(False)
            self.status.set("오류로 점검을 마치지 못했습니다.")
            self._say(f"오류로 점검을 마치지 못했습니다: {event[1].splitlines()[0]}")
            messagebox.showerror(event[2] if len(event) > 2 else "오류", event[1], parent=self)

    def _set_running(self, running: bool):
        state = "disabled" if running else "normal"
        for widget in (self.start_button, self.load_button, self.whitelist_button):
            widget.configure(state=state)
        self.stop_button.configure(state="normal" if running else "disabled")

    def _say(self, message: str):
        self._add_log(f"{datetime.now():%H:%M:%S}  {message}", simple=True)

    def _add_log(self, line: str, simple: bool):
        self.detail_log.append(line)
        del self.detail_log[:-MAX_LOG_LINES]
        if simple:
            self.simple_log.append(line)
            del self.simple_log[:-MAX_LOG_LINES]
        if simple or self.show_detail_log.get():
            self.pending_log.append(line)
            if not self.log_job:
                self.log_job = self.after(POLL_MS, self._flush_log)

    def _flush_log(self):
        if self.log_job:
            self.after_cancel(self.log_job)
            self.log_job = None
        if not self.pending_log:
            return
        lines, self.pending_log = self.pending_log, []
        self.log.configure(state="normal")
        self.log.insert("end", "\n".join(lines[-MAX_LOG_LINES:]) + "\n")
        excess = int(self.log.index("end-1c").split(".")[0]) - 1 - MAX_LOG_LINES
        if excess > 0:
            self.log.delete("1.0", f"{excess + 1}.0")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _render_log(self):
        self.pending_log = []
        lines = self.detail_log if self.show_detail_log.get() else self.simple_log
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.insert("end", "\n".join(lines) + ("\n" if lines else ""))
        self.log.see("end")
        self.log.configure(state="disabled")

    def _clear_results(self):
        self.crawl_result, self.report = None, None
        self.table.delete(*self.table.get_children())
        self.summary.set("")
        self.unchecked_button.grid_remove()
        self.unchecked_help.grid_remove()
        self._show_guide("점검이 끝나면 결과가 여기에 표시됩니다.")

    def _show_report(self, crawl: dict | None, report: dict):
        self.crawl_result, self.report = crawl, report
        self.table.delete(*self.table.get_children())
        for f in report["findings"]:
            content = " ".join(f["content"].split())[:120]
            if f.get("post_title"):
                content += f"  (글: {f['post_title'][:40]})"
            self.table.insert("", "end", iid=str(f["id"]), tags=(f["level"],), values=(
                f["level_label"], f["pattern_label"], f["category"], f["score"], content, f"{f['page_count']}개"))
        s = report["summary"]
        self.summary.set(f"발견 {s['findings']}건  (불법광고 의심 {s['high']}건 · 검토 필요 {s['suspect']}건)"
                         f"  ·  점검 페이지 {report['meta'].get('page_count', 0)}개")
        unchecked = len(report.get("unchecked", []))
        self.unchecked_button.grid_remove()
        self.unchecked_help.grid_remove()
        if unchecked:
            self.unchecked_text.set(f"⚠ 점검하지 못한 영역 {unchecked}곳")
            self.unchecked_button.grid(row=0, column=1, padx=(self.px(12), self.px(3)))
            self.unchecked_help.grid(row=0, column=2, sticky="w")
        self._relayout()
        self._show_overview()

    def _show_overview(self):
        report = self.report
        parts = []
        if report["findings"]:
            parts += [("title", "결과를 클릭하면 상세 내용이 표시됩니다.\n"),
                      ("hint", "두 번 클릭하면 해당 페이지를 브라우저로 엽니다.\n")]
        else:
            parts += [("title", "발견된 불법광고가 없습니다.\n")]
        for note in report["meta"].get("notes") or []:
            parts += [("label", "\n"), ("warn", note + "\n")]
        parts += [("label", "점검 요약\n"), ("", "\n".join(f"· {line}" for line in stats_lines(report)) + "\n")]
        if report.get("unchecked"):
            parts += [("label", "\n"), ("warn", f"점검하지 못한 영역이 {len(report['unchecked'])}곳 있습니다. "
                                                f"{UNCHECKED.when} [⚠ 점검하지 못한 영역] 버튼을 눌러 목록을 확인하세요.\n")]
        self.open_target = ""
        self._set_detail(parts)

    def _show_guide(self, message: str):
        self.open_target = ""
        self._set_detail([("hint", message + "\n")])

    def _show_unchecked(self):
        if not self.report:
            return
        items = self.report.get("unchecked", [])
        self.table.selection_remove(*self.table.selection())
        parts = [("title", f"점검하지 못한 영역 {len(items)}곳\n"),
                 ("label", UNCHECKED.labels[0] + "\n"), ("", UNCHECKED.what + "\n"),
                 ("label", UNCHECKED.labels[1] + "\n"), ("warn", UNCHECKED.when + "\n"),
                 ("hint", UNCHECKED.recommend + "\n")]
        for i, item in enumerate(items, 1):
            parts += [("label", f"{i}. {item['kind_label']}  {display_url(item['url']) or '(주소 알 수 없음)'}\n"),
                      ("", f"이유: {item['reason']}\n")]
            if item.get("host"):
                trust = "신뢰 도메인" if item.get("trusted_domain") else "신뢰 도메인 아님 - 주의"
                parts.append(("", f"도메인: {item['host']} ({trust})\n"))
            if item.get("frame_path"):
                parts.append(("", f"위치: {' ▶ '.join(item['frame_path'])}\n"))
            pages = ", ".join(display_url(p) for p in item["pages"][:3])
            more = f" 외 {item['page_count'] - 3}개" if item["page_count"] > 3 else ""
            parts.append(("hint", f"발견 페이지: {pages}{more}\n"))
        self.open_target = items[0]["url"] if items and items[0]["url"] else ""
        self._set_detail(parts)

    def _selected(self) -> dict | None:
        if not self.report or not self.table.selection():
            return None
        fid = int(self.table.selection()[0])
        return next((f for f in self.report["findings"] if f["id"] == fid), None)

    def _on_select(self, _event=None):
        f = self._selected()
        if not f:
            return
        parts = [("title", f"[{f['level_label']}] {f['pattern_label']} · {f['category']} · {f['score']}점\n")]
        if f.get("advice"):
            parts += [("label", "조치 안내\n"), ("advice", f["advice"] + "\n")]
        parts += [("label", "내용\n"), ("", f["content"] + "\n")]
        if f.get("post_title"):
            parts += [("label", "게시글 제목\n"), ("", f["post_title"] + "\n")]
        if f.get("reflected_params"):
            parts += [("label", "반사된 파라미터\n"), ("", reflected_text(f) + "\n")]
        parts += [("label", f"발견 페이지 ({f['page_count']}개)\n"),
                  ("", "\n".join(display_url(u) for u in f["pages"]) + "\n")]
        parts += [("label", "위치 (CSS 선택자)\n"), ("", (f["selector"] or "-") + "\n")]
        if f.get("frame_path"):
            parts += [("label", "iframe 경로 (바깥 → 안쪽)\n"), ("", "\n".join(f["frame_path"]) + "\n")]
        if f.get("hidden_reasons"):
            parts += [("label", "숨김 이유\n"), ("", ", ".join(f["hidden_reasons"]) + "\n")]
        if f.get("cloaking"):
            c = f["cloaking"]
            lines = [c["only_in"] + " (주소창에 직접 입력한 일반 PC 화면에는 없음)",
                     f"일반 PC 화면과 같은 단어 비율: {c['similarity']:.0%}"]
            if c["new_keywords"]:
                lines.append("새로 나타난 광고 키워드: " + ", ".join(c["new_keywords"]))
            if c["redirects"]:
                lines.append("이동하는 주소: " + ", ".join(c["redirects"][:3]))
            if c["new_hosts"]:
                lines.append("새로 나타난 외부 링크: " + ", ".join(c["new_hosts"][:5]))
            if c.get("title") and c["title"] != c.get("base_title"):
                lines.append(f"페이지 제목: '{c['base_title']}' → '{c['title']}'")
            parts += [("label", f"클로킹 비교 ({c['label']})\n"), ("warn", "\n".join(lines) + "\n")]
        if f.get("stuffing"):
            st = f["stuffing"]
            lines = [f"광고 키워드 {st['kinds']}종 {st['count']}회, 본문 글자의 {st['density']:.0%}",
                     f"키워드만 나열한 줄 {st['list_lines']}개"]
            if st.get("merged"):
                lines.append(f"이 페이지의 키워드 문구 {st['merged']}건을 이 항목으로 묶었습니다. 예: " +
                             " / ".join(st.get("examples", [])[:3]))
            parts += [("label", "키워드 도배 분석\n"), ("", "\n".join(lines) + "\n")]
        if f.get("urls"):
            parts += [("label", "연결된 주소\n"), ("", "\n".join(f["urls"]) + "\n")]
        parts += [("label", "판정 근거\n"),
                  ("", "\n".join(f"· {e['label']} (+{e['points']}점)" for e in f["evidence"]) + "\n")]
        self.open_target = f["pages"][0] if f["pages"] else ""
        self._set_detail(parts)

    def _set_detail(self, parts: list[tuple[str, str]]):
        self.detail.configure(state="normal")
        self.detail.delete("1.0", "end")
        for tag, text in parts:
            self.detail.insert("end", text, tag or ())
        self.detail.configure(state="disabled")

    def _open_page(self):
        f = self._selected()
        target = f["pages"][0] if f and f["pages"] else self.open_target
        if target:
            webbrowser.open(target)

    def _copy_selector(self):
        f = self._selected()
        if f:
            self.clipboard_clear()
            self.clipboard_append(location_text(f))
            self.status.set("위치(선택자)를 클립보드에 복사했습니다.")

    def _load_result(self):
        path = filedialog.askopenfilename(title="저장된 점검 결과 선택", initialdir=output_dir(),
                                          filetypes=[("점검 결과 JSON", "*.json")])
        if not path:
            return
        try:
            data = load_json(path)
        except Exception as e:
            messagebox.showerror("불러오기 실패", f"JSON 파일을 읽지 못했습니다.\n{e}")
            return
        if "pages" in data:
            report = detect(data)
            self._say(f"{Path(path).name}: 페이지 {len(data['pages'])}개로 탐지를 다시 실행했습니다.")
            self._show_report(data, report)
            self.status.set("저장된 점검 결과로 탐지를 다시 실행했습니다.")
        elif "findings" in data:
            self._show_report(None, data)
            self.status.set("저장된 탐지 결과를 불러왔습니다. (다시 탐지하려면 crawl_*.json 파일을 선택하세요)")
        else:
            messagebox.showwarning("형식 오류", "AD Sentinel 점검 결과 파일이 아닙니다.")

    def _edit_whitelist(self):
        dialog = tk.Toplevel(self)
        dialog.title("신뢰 도메인 관리")
        dialog.transient(self)
        _set_icon(dialog)
        frame = ttk.Frame(dialog, padding=self.px(12))
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, wraplength=self.px(520), justify="left",
                  text="신뢰 도메인으로 연결되는 링크·iframe은 '외부 도메인' 근거에서 제외됩니다.\n"
                       "기본 신뢰 도메인: " + ", ".join(DEFAULT_WHITELIST) + "\n\n"
                       "추가할 도메인을 한 줄에 하나씩 입력하세요. 하위 도메인도 함께 신뢰합니다. (예: nia.or.kr)").pack(
            fill="x")
        text = tk.Text(frame, height=12, relief="flat", highlightthickness=1, highlightbackground="#d0d4da",
                       font="TkTextFont")
        text.pack(fill="both", expand=True, pady=self.px(8))
        text.insert("1.0", "\n".join(read_user_whitelist()))

        def save():
            path = save_user_whitelist(text.get("1.0", "end").splitlines())
            dialog.destroy()
            self._say(f"신뢰 도메인을 저장했습니다. ({path.name})")
            if self.crawl_result:
                self._show_report(self.crawl_result, detect(self.crawl_result))
                self.status.set("변경한 신뢰 도메인으로 탐지를 다시 실행했습니다.")

        buttons = ttk.Frame(frame)
        buttons.pack(fill="x")
        ttk.Button(buttons, text="저장", command=save, style="Accent.TButton").pack(side="right")
        ttk.Button(buttons, text="취소", command=dialog.destroy).pack(side="right", padx=self.px(6))
        dialog.geometry(f"{self.px(580)}x{self.px(460)}")

    def _export(self, kind: str, extension: str, writer):
        if not self.report:
            messagebox.showinfo("결과 없음", "먼저 점검을 실행하거나 결과를 불러오세요.")
            return
        name = f"불법광고점검_{datetime.now():%Y%m%d_%H%M}.{extension}"
        path = filedialog.asksaveasfilename(title=f"{kind} 저장", initialdir=output_dir(), initialfile=name,
                                            defaultextension=f".{extension}", filetypes=[(kind, f"*.{extension}")])
        if path:
            writer(self.report, path)
            self._say(f"{kind}를 저장했습니다: {path}")
            if extension == "html" and messagebox.askyesno("저장 완료", "보고서를 저장했습니다. 지금 열어 볼까요?"):
                webbrowser.open(Path(path).resolve().as_uri())

    def _export_html(self):
        self._export("HTML 보고서", "html", export_html)

    def _export_csv(self):
        self._export("CSV", "csv", export_csv)

    def _export_json(self):
        self._export("JSON", "json", export_json)

    def _on_close(self):
        if self.worker and self.worker.is_alive():
            if not messagebox.askyesno("종료", "점검이 진행 중입니다. 중지하고 종료할까요?"):
                return
            self.stop_event.set()
        logging.getLogger("ad_sentinel").removeHandler(self.log_handler)
        self.destroy()


def _eta_text(done: int, total: int, elapsed: float) -> str:
    if done <= 0 or total <= done or elapsed <= 0:
        return ""
    remaining = int((total - done) * elapsed / done)
    minutes, seconds = divmod(remaining, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f" · 남은 시간 약 {hours}시간 {minutes}분"
    if minutes:
        return f" · 남은 시간 약 {minutes}분 {seconds}초"
    return f" · 남은 시간 약 {seconds}초"


def _page_message(index: int, page: dict, findings: int, unchecked: int) -> str:
    if page.get("error"):
        return f"{index}번째 페이지를 열지 못했습니다: {display_url(page['url'])[:80]}"
    title = " ".join((page.get("title") or display_url(page.get("final_url") or page["url"])).split())
    if len(title) > 50:
        title = title[:50] + "…"
    result = f"의심 {findings}건" if findings else "이상 없음"
    if unchecked:
        result += f", 점검하지 못한 영역 {unchecked}곳"
    return f"{index}번째 페이지 점검 완료: {title} ({result})"


def _font_of(style_name: str) -> font.Font | None:
    name = ttk.Style().lookup(style_name, "font")
    if not name:
        return None
    try:
        return font.nametofont(name)
    except tk.TclError:
        return font.Font(font=name)


def _bold_font() -> tuple:
    base = font.nametofont("TkDefaultFont")
    return (base.actual("family"), base.actual("size"), "bold")


def load_ui_settings() -> dict:
    try:
        data = json.loads((data_dir() / UI_SETTINGS_FILE).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_ui_settings(settings: dict) -> None:
    try:
        (data_dir() / UI_SETTINGS_FILE).write_text(json.dumps(settings, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def light_theme_name(style: ttk.Style) -> str:
    names = style.theme_names()
    return next((n for n in ("vista", "xpnative", "winnative", "clam") if n in names), style.theme_use())


def _theme_background(root: tk.Misc) -> str:
    return ttk.Style(root).lookup("TFrame", "background") or "#f0f0f0"


def _apply_theme(root: tk.Tk, scale: float, light: bool = False):
    style = ttk.Style(root)
    if light:
        style.theme_use(light_theme_name(style))
    else:
        try:
            import sv_ttk
            sv_ttk.set_theme("light")
        except Exception:
            pass
    scaled = root.__dict__.setdefault("_scaled_fonts", set())
    families = set(font.families(root))
    korean = next((f for f in KOREAN_FONTS if f in families), None)
    for name in font.names(root):
        if not name.startswith(("Tk", "SunValley")) or name == "TkFixedFont" or name in scaled:
            continue
        scaled.add(name)
        f = font.nametofont(name)
        options = {}
        size = int(f.cget("size"))
        if size < 0:
            options["size"] = -round(-size * scale)
        if korean:
            if "semibold" in f.cget("family").lower() or "bold" in f.cget("family").lower():
                options["weight"] = "bold"
            options["family"] = korean
        if options:
            f.configure(**options)


def _set_icon(window: tk.Tk) -> list[str]:
    problems = []
    ico = str(asset_path("icon.ico"))
    if winicon.is_windows():
        try:
            window.iconbitmap(default=ico)
        except tk.TclError as e:
            problems.append(f"iconbitmap: {e}")
    images = []
    for size in ICON_PHOTO_SIZES:
        path = asset_path("icon.png" if size == 256 else f"icon_{size}.png")
        try:
            images.append(tk.PhotoImage(master=window, file=str(path)))
        except tk.TclError as e:
            problems.append(f"{path.name}: {e}")
    if images:
        try:
            window.iconphoto(True, *images)
        except tk.TclError as e:
            problems.append(f"iconphoto: {e}")
    window._icon_images = images
    return problems


def _set_native_icon(window: tk.Tk) -> str:
    if not winicon.is_windows():
        return ""
    try:
        window._icon_handles = winicon.set_native_icon(window, str(asset_path("icon.ico")))
    except (OSError, tk.TclError, ValueError) as e:
        return f"WM_SETICON: {e}"
    return ""


def write_error_log(context: str) -> Path:
    path = data_dir() / "error.log"
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] v{__version__} {context}\n{traceback.format_exc()}\n")
    except OSError:
        pass
    return path


def _show_startup_error(path: Path) -> None:
    try:
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(APP_TITLE, "프로그램을 시작하지 못했습니다.\n\n"
                                        f"오류 기록 파일을 담당자에게 보내 주세요:\n{path}", parent=root)
        root.destroy()
    except tk.TclError:
        pass


def run_gui():
    winicon.set_dpi_awareness()
    winicon.set_app_user_model_id()
    try:
        app = App()
    except Exception:
        _show_startup_error(write_error_log("시작 오류"))
        raise
    app.mainloop()
