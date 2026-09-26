import logging
import queue
import threading
import tkinter as tk
import webbrowser
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, font, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from ad_sentinel import __version__
from ad_sentinel.config import OWN_SITE_LABEL, ROBOTS_IGNORE_WARNING, CrawlConfig
from ad_sentinel.crawler import Crawler
from ad_sentinel.detector import detect
from ad_sentinel.detector.domains import DEFAULT_WHITELIST, read_user_whitelist, save_user_whitelist
from ad_sentinel.paths import output_dir
from ad_sentinel.report import display_url, export_csv, export_html, export_json, location_text, reflected_text
from ad_sentinel.storage import load_json, save_json
from ad_sentinel.url_list import load_url_list

APP_TITLE = "AD Sentinel - 공공 웹사이트 불법광고 점검"
SITE, LIST = "site", "list"
LEVEL_COLORS = {"high": "#fde2e1", "suspect": "#fff1d6"}
LIST_FILE_TYPES = [("주소 목록 파일", "*.txt *.csv *.tsv *.zip"), ("모든 파일", "*.*")]


class QueueLogHandler(logging.Handler):
    def __init__(self, events: queue.Queue):
        super().__init__(logging.INFO)
        self.events = events
        self.setFormatter(logging.Formatter("%(asctime)s %(message)s", "%H:%M:%S"))

    def emit(self, record):
        self.events.put(("log", self.format(record)))


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1200x860")
        self.minsize(980, 700)
        _setup_fonts(self)

        self.events: queue.Queue = queue.Queue()
        self.stop_event = threading.Event()
        self.worker: threading.Thread | None = None
        self.crawl_result: dict | None = None
        self.report: dict | None = None
        self.url_list: list[str] = []

        self.mode = tk.StringVar(value=SITE)
        self.start_url = tk.StringVar()
        self.max_pages = tk.IntVar(value=30)
        self.max_depth = tk.IntVar(value=3)
        self.own_site = tk.BooleanVar(value=False)
        self.list_info = tk.StringVar(value="불러온 목록 없음")
        self.status = tk.StringVar(value="점검할 사이트 주소를 입력하고 [점검 시작]을 누르세요.")
        self.count_text = tk.StringVar(value="")
        self.summary = tk.StringVar(value="")

        self._build()
        self._on_mode_change()

        self.log_handler = QueueLogHandler(self.events)
        logging.getLogger("ad_sentinel").addHandler(self.log_handler)
        logging.getLogger("ad_sentinel").setLevel(logging.INFO)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(100, self._poll_events)

    def _build(self):
        root = ttk.Frame(self, padding=10)
        root.pack(fill="both", expand=True)

        mode_box = ttk.LabelFrame(root, text="1. 점검 방식", padding=8)
        mode_box.pack(fill="x")
        ttk.Radiobutton(mode_box, text="사이트 점검 - 시작 주소에서 링크를 따라가며 하위 페이지를 점검",
                        variable=self.mode, value=SITE, command=self._on_mode_change).pack(anchor="w")
        ttk.Radiobutton(mode_box, text="URL 목록 점검 - 주소 목록 파일(서치 콘솔에서 내보낸 파일 등)에 있는 주소만 점검",
                        variable=self.mode, value=LIST, command=self._on_mode_change).pack(anchor="w")

        target = ttk.LabelFrame(root, text="2. 점검 대상", padding=8)
        target.pack(fill="x", pady=(8, 0))

        self.site_frame = ttk.Frame(target)
        ttk.Label(self.site_frame, text="시작 주소").grid(row=0, column=0, sticky="w")
        url_entry = ttk.Entry(self.site_frame, textvariable=self.start_url, width=70)
        url_entry.grid(row=0, column=1, columnspan=5, sticky="we", padx=6)
        url_entry.bind("<Return>", lambda e: self._start())
        ttk.Label(self.site_frame, text="예: https://www.example.go.kr", foreground="#666").grid(
            row=0, column=6, sticky="w")
        ttk.Label(self.site_frame, text="최대 페이지 수").grid(row=1, column=0, sticky="w", pady=(6, 0))
        ttk.Spinbox(self.site_frame, from_=1, to=5000, textvariable=self.max_pages, width=8).grid(
            row=1, column=1, sticky="w", padx=6, pady=(6, 0))
        ttk.Label(self.site_frame, text="링크 깊이").grid(row=1, column=2, sticky="w", pady=(6, 0))
        ttk.Spinbox(self.site_frame, from_=0, to=10, textvariable=self.max_depth, width=6).grid(
            row=1, column=3, sticky="w", padx=6, pady=(6, 0))
        ttk.Label(self.site_frame, text="(시작 주소에서 링크를 몇 번까지 따라갈지)", foreground="#666").grid(
            row=1, column=4, sticky="w", pady=(6, 0))
        self.site_frame.columnconfigure(5, weight=1)

        self.list_frame = ttk.Frame(target)
        ttk.Button(self.list_frame, text="목록 파일 불러오기...", command=self._load_list).grid(
            row=0, column=0, sticky="w")
        ttk.Label(self.list_frame, textvariable=self.list_info).grid(row=0, column=1, sticky="w", padx=8)
        ttk.Label(self.list_frame, foreground="#666",
                  text="txt(한 줄에 주소 하나), CSV(첫 번째 열), 구글 서치 콘솔 '내보내기' 파일(csv 또는 zip)을 읽습니다. "
                       "목록의 주소만 점검하고 링크는 따라가지 않습니다.").grid(
            row=1, column=0, columnspan=2, sticky="w", pady=(6, 0))
        self.list_frame.columnconfigure(1, weight=1)

        ttk.Checkbutton(target, text=OWN_SITE_LABEL, variable=self.own_site,
                        command=self._on_own_site).pack(anchor="w", side="bottom", pady=(8, 0))

        buttons = ttk.Frame(root)
        buttons.pack(fill="x", pady=8)
        self.start_button = ttk.Button(buttons, text="▶ 점검 시작", command=self._start)
        self.start_button.pack(side="left")
        self.stop_button = ttk.Button(buttons, text="■ 중지", command=self._stop, state="disabled")
        self.stop_button.pack(side="left", padx=6)
        self.load_button = ttk.Button(buttons, text="저장된 점검 결과 불러오기...", command=self._load_result)
        self.load_button.pack(side="right")
        self.whitelist_button = ttk.Button(buttons, text="신뢰 도메인 관리...", command=self._edit_whitelist)
        self.whitelist_button.pack(side="right", padx=6)

        progress = ttk.LabelFrame(root, text="3. 진행 상황", padding=8)
        progress.pack(fill="x")
        top = ttk.Frame(progress)
        top.pack(fill="x")
        ttk.Label(top, textvariable=self.status).pack(side="left")
        ttk.Label(top, textvariable=self.count_text).pack(side="right")
        self.progress = ttk.Progressbar(progress, mode="determinate")
        self.progress.pack(fill="x", pady=4)
        self.log = ScrolledText(progress, height=6, state="disabled", wrap="none")
        self.log.pack(fill="x")

        results = ttk.LabelFrame(root, text="4. 점검 결과", padding=8)
        results.pack(fill="both", expand=True, pady=(8, 0))
        header = ttk.Frame(results)
        header.pack(fill="x")
        ttk.Label(header, textvariable=self.summary, font=("TkDefaultFont", 10, "bold")).pack(side="left")
        for text, command in [("HTML 보고서", self._export_html), ("CSV", self._export_csv), ("JSON", self._export_json)]:
            ttk.Button(header, text=f"{text}로 저장", command=command).pack(side="right", padx=(6, 0))

        panes = ttk.PanedWindow(results, orient="horizontal")
        panes.pack(fill="both", expand=True, pady=(6, 0))

        table_frame = ttk.Frame(panes)
        columns = [("level", "판정", 95), ("pattern", "유형", 140), ("category", "분류", 70),
                   ("score", "점수", 45), ("content", "내용", 280), ("pages", "페이지 수", 75)]
        self.table = ttk.Treeview(table_frame, columns=[c for c, _, _ in columns], show="headings", selectmode="browse")
        for key, title, width in columns:
            self.table.heading(key, text=title)
            self.table.column(key, width=width, anchor="w" if key == "content" else "center",
                              stretch=key == "content")
        for level, color in LEVEL_COLORS.items():
            self.table.tag_configure(level, background=color)
        scroll = ttk.Scrollbar(table_frame, orient="vertical", command=self.table.yview)
        self.table.configure(yscrollcommand=scroll.set)
        self.table.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.table.bind("<<TreeviewSelect>>", self._on_select)
        self.table.bind("<Double-1>", lambda e: self._open_page())
        panes.add(table_frame, weight=3)

        detail_frame = ttk.Frame(panes)
        self.detail = ScrolledText(detail_frame, width=48, wrap="word", state="disabled")
        self.detail.tag_configure("title", font=("TkDefaultFont", 11, "bold"))
        self.detail.tag_configure("label", font=("TkDefaultFont", 10, "bold"), spacing1=6)
        self.detail.tag_configure("advice", background="#eef6ff", lmargin1=4, lmargin2=4)
        self.detail.pack(fill="both", expand=True)
        detail_buttons = ttk.Frame(detail_frame)
        detail_buttons.pack(fill="x", pady=(4, 0))
        ttk.Button(detail_buttons, text="페이지 열기", command=self._open_page).pack(side="left")
        ttk.Button(detail_buttons, text="위치(선택자) 복사", command=self._copy_selector).pack(side="left", padx=6)
        panes.add(detail_frame, weight=2)

    def _on_mode_change(self):
        if self.mode.get() == SITE:
            self.list_frame.pack_forget()
            self.site_frame.pack(fill="x")
        else:
            self.site_frame.pack_forget()
            self.list_frame.pack(fill="x")

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
        self._append_log(f"목록 파일 {Path(path).name}: 주소 {len(urls)}개 (첫 주소: {urls[0]})")

    def _make_config(self) -> CrawlConfig | None:
        common = dict(respect_robots=not self.own_site.get())
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
        return CrawlConfig(start_url=url, max_pages=max(1, max_pages), max_depth=max(0, max_depth), **common)

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
        self.worker = threading.Thread(target=self._work, args=(config,), daemon=True)
        self.worker.start()

    def _work(self, config: CrawlConfig):
        try:
            crawler = Crawler(config, on_progress=self._on_progress, stop_event=self.stop_event)
            crawl = crawler.run()
            crawl_path = save_json(crawl, prefix="crawl")
            report = detect(crawl)
            report_path = save_json(report, prefix="detect")
            self.events.put(("done", crawl, report, crawl_path, report_path))
        except Exception as e:
            logging.getLogger("ad_sentinel").exception("점검 중 오류")
            self.events.put(("error", str(e)))

    def _on_progress(self, done: int, total: int, url: str):
        self.events.put(("progress", done, total, url))

    def _stop(self):
        self.stop_event.set()
        self.stop_button.configure(state="disabled")
        self.status.set("중지하는 중입니다. 지금 점검 중인 페이지를 마치고 멈춥니다...")

    def _poll_events(self):
        try:
            while True:
                event = self.events.get_nowait()
                kind = event[0]
                if kind == "log":
                    self._append_log(event[1])
                elif kind == "progress":
                    _, done, total, url = event
                    self.progress.configure(maximum=max(total, 1), value=done)
                    self.count_text.set(f"{done} / {total}")
                    if url and not self.stop_event.is_set():
                        self.status.set(f"점검 중: {url}")
                elif kind == "done":
                    _, crawl, report, crawl_path, report_path = event
                    self._set_running(False)
                    stopped = crawl["meta"].get("stopped_by_user")
                    self.status.set(("사용자가 중지함. " if stopped else "점검 완료. ") +
                                    f"페이지 {len(crawl['pages'])}개를 점검했습니다.")
                    checked = len(crawl["pages"])
                    if not stopped:
                        self.progress.configure(maximum=max(checked, 1))
                    self.progress.configure(value=checked)
                    self.count_text.set(f"{checked}페이지 점검")
                    self._append_log(f"점검 결과 저장: {crawl_path}")
                    self._append_log(f"탐지 결과 저장: {report_path}")
                    self._show_report(crawl, report)
                elif kind == "error":
                    self._set_running(False)
                    self.status.set("오류로 점검을 마치지 못했습니다.")
                    messagebox.showerror("오류", event[1])
        except queue.Empty:
            pass
        self.after(100, self._poll_events)

    def _set_running(self, running: bool):
        state = "disabled" if running else "normal"
        for widget in (self.start_button, self.load_button, self.whitelist_button):
            widget.configure(state=state)
        self.stop_button.configure(state="normal" if running else "disabled")

    def _append_log(self, line: str):
        self.log.configure(state="normal")
        self.log.insert("end", line + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _clear_results(self):
        self.crawl_result, self.report = None, None
        self.table.delete(*self.table.get_children())
        self._set_detail([])
        self.summary.set("")

    def _show_report(self, crawl: dict | None, report: dict):
        self.crawl_result, self.report = crawl, report
        self.table.delete(*self.table.get_children())
        for f in report["findings"]:
            content = " ".join(f["content"].split())[:120]
            self.table.insert("", "end", iid=str(f["id"]), tags=(f["level"],), values=(
                f["level_label"], f["pattern_label"], f["category"], f["score"], content,
                f"{f['page_count']}개"))
        s = report["summary"]
        self.summary.set(f"발견 {s['findings']}건  (불법광고 의심 {s['high']}건 · 검토 필요 {s['suspect']}건)  "
                         f"· 점검 페이지 {report['meta'].get('page_count', 0)}개")
        if report["findings"]:
            first = str(report["findings"][0]["id"])
            self.table.selection_set(first)
            self.table.focus(first)
        else:
            self._set_detail([("title", "발견된 불법광고가 없습니다.\n")])

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
        if f.get("reflected_params"):
            parts += [("label", "반사된 파라미터\n"), ("", reflected_text(f) + "\n")]
        parts += [("label", f"발견 페이지 ({f['page_count']}개)\n"),
                  ("", "\n".join(display_url(u) for u in f["pages"]) + "\n")]
        parts += [("label", "위치 (CSS 선택자)\n"), ("", (f["selector"] or "-") + "\n")]
        if f.get("frame_path"):
            parts += [("label", "iframe 경로 (바깥 → 안쪽)\n"), ("", "\n".join(f["frame_path"]) + "\n")]
        if f.get("hidden_reasons"):
            parts += [("label", "숨김 이유\n"), ("", ", ".join(f["hidden_reasons"]) + "\n")]
        if f.get("urls"):
            parts += [("label", "연결된 주소\n"), ("", "\n".join(f["urls"]) + "\n")]
        parts += [("label", "판정 근거\n"),
                  ("", "\n".join(f"· {e['label']} (+{e['points']}점)" for e in f["evidence"]) + "\n")]
        self._set_detail(parts)

    def _set_detail(self, parts: list[tuple[str, str]]):
        self.detail.configure(state="normal")
        self.detail.delete("1.0", "end")
        for tag, text in parts:
            self.detail.insert("end", text, tag or ())
        self.detail.configure(state="disabled")

    def _open_page(self):
        f = self._selected()
        if f and f["pages"]:
            webbrowser.open(f["pages"][0])

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
            self._append_log(f"{Path(path).name}: 페이지 {len(data['pages'])}개로 탐지를 다시 실행했습니다.")
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
        dialog.geometry("560x480")
        dialog.transient(self)
        ttk.Label(dialog, padding=8, wraplength=530, justify="left",
                  text="신뢰 도메인으로 연결되는 링크·iframe은 '외부 도메인' 근거에서 제외됩니다.\n"
                       "기본 신뢰 도메인: " + ", ".join(DEFAULT_WHITELIST) + "\n\n"
                       "추가할 도메인을 한 줄에 하나씩 입력하세요. 하위 도메인도 함께 신뢰합니다. (예: nia.or.kr)").pack(
            fill="x")
        text = tk.Text(dialog, height=14)
        text.pack(fill="both", expand=True, padx=8)
        text.insert("1.0", "\n".join(read_user_whitelist()))

        def save():
            path = save_user_whitelist(text.get("1.0", "end").splitlines())
            dialog.destroy()
            self._append_log(f"신뢰 도메인 저장: {path}")
            if self.crawl_result:
                self._show_report(self.crawl_result, detect(self.crawl_result))
                self.status.set("변경한 신뢰 도메인으로 탐지를 다시 실행했습니다.")

        ttk.Button(dialog, text="저장", command=save).pack(side="right", padx=8, pady=8)
        ttk.Button(dialog, text="취소", command=dialog.destroy).pack(side="right", pady=8)

    def _export(self, kind: str, extension: str, writer):
        if not self.report:
            messagebox.showinfo("결과 없음", "먼저 점검을 실행하거나 결과를 불러오세요.")
            return
        name = f"불법광고점검_{datetime.now():%Y%m%d_%H%M}.{extension}"
        path = filedialog.asksaveasfilename(title=f"{kind} 저장", initialdir=output_dir(), initialfile=name,
                                            defaultextension=f".{extension}", filetypes=[(kind, f"*.{extension}")])
        if path:
            writer(self.report, path)
            self._append_log(f"{kind} 저장: {path}")
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


def _setup_fonts(root: tk.Tk):
    families = set(font.families(root))
    for family in ("Malgun Gothic", "맑은 고딕", "Noto Sans CJK KR", "NanumGothic", "WenQuanYi Zen Hei"):
        if family in families:
            for name in ("TkDefaultFont", "TkTextFont", "TkHeadingFont", "TkMenuFont"):
                font.nametofont(name).configure(family=family, size=10)
            break


def run_gui():
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    app = App()
    app.title(f"{APP_TITLE} (v{__version__})")
    app.mainloop()
