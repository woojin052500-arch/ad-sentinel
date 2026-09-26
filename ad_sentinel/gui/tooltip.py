import tkinter as tk
from tkinter import font, ttk
from typing import Callable

from ad_sentinel.help_texts import Help, tooltip_text

TIP_BACKGROUND = "#ffffff"
TIP_BORDER = "#9ca3af"
TIP_FOREGROUND = "#111827"
ICON_FILL = "#e8eef8"
ICON_OUTLINE = "#7b8aa3"
ICON_TEXT = "#2f4a78"


def help_content(item: Help) -> tuple[str, str]:
    return item.title, tooltip_text(item)


class Tooltip:
    def __init__(self, widget: tk.Widget, content: Callable[[tk.Event | None], tuple[str, str] | None],
                 wrap_px: int, delay_ms: int = 250):
        self.widget = widget
        self.content = content
        self.wrap_px = wrap_px
        self.delay_ms = delay_ms
        self.window: tk.Toplevel | None = None
        self.shown: tuple[str, str] | None = None
        self.pending: str | None = None
        widget.bind("<Enter>", self._on_motion, add="+")
        widget.bind("<Motion>", self._on_motion, add="+")
        widget.bind("<Leave>", lambda e: self.hide(), add="+")
        widget.bind("<ButtonPress>", lambda e: self.hide(), add="+")
        widget.bind("<Destroy>", lambda e: self.hide(), add="+")

    def _on_motion(self, event: tk.Event):
        data = self.content(event)
        if data == self.shown and self.window:
            return
        self.hide()
        if data:
            x, y = event.x_root, event.y_root
            self.pending = self.widget.after(self.delay_ms, lambda: self.show(data, x, y))

    def show(self, data: tuple[str, str], x: int | None = None, y: int | None = None):
        self.hide()
        if x is None or y is None:
            x = self.widget.winfo_rootx() + self.widget.winfo_width() // 2
            y = self.widget.winfo_rooty() + self.widget.winfo_height() // 2
        title, body = data
        window = tk.Toplevel(self.widget)
        window.wm_overrideredirect(True)
        try:
            window.attributes("-topmost", True)
        except tk.TclError:
            pass
        frame = tk.Frame(window, background=TIP_BACKGROUND, highlightthickness=1, highlightbackground=TIP_BORDER,
                         padx=10, pady=8)
        frame.pack()
        base = font.nametofont("TkDefaultFont")
        bold = (base.actual("family"), base.actual("size"), "bold")
        tk.Label(frame, text=title, font=bold, background=TIP_BACKGROUND, foreground=TIP_FOREGROUND,
                 justify="left", anchor="w").pack(fill="x")
        tk.Label(frame, text=body, background=TIP_BACKGROUND, foreground=TIP_FOREGROUND, justify="left",
                 anchor="w", wraplength=self.wrap_px).pack(fill="x", pady=(4, 0))
        window.update_idletasks()
        width, height = window.winfo_reqwidth(), window.winfo_reqheight()
        screen_w, screen_h = window.winfo_screenwidth(), window.winfo_screenheight()
        left = min(x + 14, screen_w - width - 8)
        top = y + 18 if y + 18 + height < screen_h else y - height - 10
        window.wm_geometry(f"+{max(0, left)}+{max(0, top)}")
        self.window, self.shown = window, data

    def hide(self):
        if self.pending:
            try:
                self.widget.after_cancel(self.pending)
            except tk.TclError:
                pass
            self.pending = None
        if self.window:
            try:
                self.window.destroy()
            except tk.TclError:
                pass
        self.window, self.shown = None, None


class HelpIcon(tk.Canvas):
    def __init__(self, parent: tk.Widget, item: Help, size: int, wrap_px: int):
        background = ttk.Style(parent).lookup("TFrame", "background") or "#fafafa"
        super().__init__(parent, width=size, height=size, highlightthickness=0, borderwidth=0,
                         background=background, cursor="question_arrow", takefocus=0)
        self.item = item
        inset = max(1, size // 12)
        self.create_oval(inset, inset, size - inset, size - inset, fill=ICON_FILL, outline=ICON_OUTLINE)
        base = font.nametofont("TkDefaultFont")
        self.create_text(size / 2, size / 2 + 0.5, text="?", fill=ICON_TEXT,
                         font=(base.actual("family"), -max(9, int(size * 0.72)), "bold"))
        self.tooltip = Tooltip(self, lambda e: help_content(item), wrap_px)
        self.bind("<ButtonRelease-1>", lambda e: self.tooltip.show(help_content(item)), add="+")

    def text(self) -> str:
        return tooltip_text(self.item)
