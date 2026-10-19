"""Main window: branded sidebar + one screen at a time. Owns the folder, scan, journal and worker."""

from __future__ import annotations

import os
import sys
import webbrowser
from pathlib import Path

import customtkinter as ctk

from . import theme as t
from . import widgets
from .views.duplicates import DuplicatesView
from .views.history import HistoryView
from .views.organize import OrganizeView
from .views.overview import OverviewView
from .worker import Worker
from ..config import APP_NAME, APP_SHORT, AUTHOR, SITE_LABEL, SITE_URL, VERSION
from ..core.actions import Journal
from ..core.errors import CleanerError
from ..core.rules import default_guard
from ..settings import Settings

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    _DnDMixin = TkinterDnD.DnDWrapper
except ImportError:
    TkinterDnD = DND_FILES = None
    _DnDMixin = object

NAV = [
    ("overview", "Overview", OverviewView),
    ("duplicates", "Duplicates", DuplicatesView),
    ("organize", "Organize", OrganizeView),
    ("history", "History & undo", HistoryView),
]


def asset(name: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    return base / "assets" / name


class App(ctk.CTk, _DnDMixin):
    def __init__(self):
        super().__init__(fg_color=t.BG)
        t.apply()
        if TkinterDnD is not None:
            try:
                TkinterDnD._require(self)
                widgets.DND_READY = True
            except Exception:
                widgets.DND_READY = False

        self.title(APP_NAME)
        self.geometry("1200x800")
        self.minsize(1040, 700)
        icon = asset("app.ico")
        if sys.platform == "win32" and icon.exists():
            self.iconbitmap(str(icon))
        t.style_tables(self)

        self.settings = Settings()
        self.worker = Worker(self)
        self.guard = default_guard()
        self.journal = Journal()
        self.folder = ""
        self.scan = None       # last ScanResult for self.folder (shared by Overview and Duplicates)
        saved = self.settings.get("folder", "")
        if saved and os.path.isdir(saved) and not self.guard.is_protected(saved):
            self.folder = saved

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self._build_sidebar()
        self.stage = ctk.CTkFrame(self, fg_color=t.BG, corner_radius=0)
        self.stage.grid(row=0, column=1, sticky="nsew")
        self.stage.grid_columnconfigure(0, weight=1)
        self.stage.grid_rowconfigure(0, weight=1)

        self.views: dict[str, ctk.CTkFrame] = {}
        self.current = None
        self.show("overview")
        self.protocol("WM_DELETE_WINDOW", self._close)

        if widgets.DND_READY and DND_FILES:  # drop a folder anywhere on the window
            self.drop_target_register(DND_FILES)
            self.dnd_bind("<<Drop>>", self._dropped)

    # ----- sidebar -----
    def _build_sidebar(self) -> None:
        side = ctk.CTkFrame(self, width=236, fg_color=t.SIDEBAR, corner_radius=0)
        side.grid(row=0, column=0, sticky="nsw")
        side.grid_propagate(False)
        side.grid_columnconfigure(0, weight=1)

        brand = ctk.CTkFrame(side, fg_color="transparent")
        brand.grid(row=0, column=0, sticky="ew", padx=20, pady=(26, 30))
        self._logo(brand).grid(row=0, column=0, rowspan=2, padx=(0, 12))
        ctk.CTkLabel(brand, text=APP_SHORT, font=t.font(17, "bold"), text_color=t.TEXT,
                     anchor="w").grid(row=0, column=1, sticky="sw")
        ctk.CTkLabel(brand, text=f"by {AUTHOR}", font=t.font(11), text_color=t.MUTED,
                     anchor="w").grid(row=1, column=1, sticky="nw")

        ctk.CTkLabel(side, text="TOOLS", font=t.font(11, "bold"), text_color=t.FAINT,
                     anchor="w").grid(row=1, column=0, sticky="ew", padx=24, pady=(0, 6))
        self.nav_buttons: dict[str, tuple[ctk.CTkFrame, ctk.CTkButton]] = {}
        for i, (key, label, _view) in enumerate(NAV):
            holder = ctk.CTkFrame(side, fg_color="transparent")
            holder.grid(row=2 + i, column=0, sticky="ew", padx=(0, 14), pady=2)
            holder.grid_columnconfigure(1, weight=1)
            bar = ctk.CTkFrame(holder, width=3, height=26, corner_radius=2, fg_color="transparent")
            bar.grid(row=0, column=0, padx=(0, 11))
            btn = ctk.CTkButton(holder, text=label, anchor="w", height=38, corner_radius=8,
                                fg_color="transparent", hover_color=t.SURFACE, text_color=t.MUTED,
                                text_color_disabled=t.FAINT, font=t.font(14),
                                command=lambda k=key: self.show(k))
            btn.grid(row=0, column=1, sticky="ew")
            self.nav_buttons[key] = (bar, btn)

        side.grid_rowconfigure(20, weight=1)
        foot = ctk.CTkFrame(side, fg_color="transparent")
        foot.grid(row=21, column=0, sticky="ew", padx=24, pady=(0, 22))

        safe = ctk.CTkFrame(foot, fg_color=t.SURFACE, corner_radius=8)
        safe.pack(fill="x", pady=(0, 16))
        ctk.CTkLabel(safe, text="●", font=t.font(10), width=12,
                     text_color=t.SUCCESS).pack(side="left", padx=(10, 6), pady=8)
        ctk.CTkLabel(safe, text="Recycle Bin only", font=t.font(12),
                     text_color=t.TEXT).pack(side="left")

        ctk.CTkLabel(foot, text="Nothing is deleted for good, and nothing leaves your PC.",
                     font=t.font(11), text_color=t.FAINT, anchor="w", justify="left",
                     wraplength=186).pack(fill="x")
        link = ctk.CTkLabel(foot, text=SITE_LABEL, font=t.font(12), text_color=t.BLUE,
                            anchor="w", cursor="hand2")
        link.pack(fill="x", pady=(8, 0))
        link.bind("<Button-1>", lambda _e: webbrowser.open(SITE_URL))
        ctk.CTkLabel(foot, text=f"v{VERSION}", font=t.mono(10), text_color=t.FAINT,
                     anchor="w").pack(fill="x")

    def _logo(self, master) -> ctk.CTkLabel:
        """Uses assets/logo.png (the MJC mark) when present; otherwise a gold monogram."""
        path = asset("logo.png")
        if path.exists():
            from PIL import Image
            img = ctk.CTkImage(Image.open(path), size=(40, 40))
            return ctk.CTkLabel(master, image=img, text="")
        return ctk.CTkLabel(master, text="MJC", width=42, height=42, corner_radius=10,
                            fg_color=t.GOLD, text_color=t.ON_GOLD, font=t.font(13, "bold"))

    # ----- navigation -----
    def show(self, key: str) -> None:
        if self.worker.busy:
            return
        if key not in self.views:
            view_cls = next(v for k, _l, v in NAV if k == key)
            self.views[key] = view_cls(self.stage, self)
        if self.current:
            self.current.grid_remove()
        self.current = self.views[key]
        self.current.grid(row=0, column=0, sticky="nsew")
        self.current.on_show()
        for k, (bar, btn) in self.nav_buttons.items():
            active = k == key
            bar.configure(fg_color=t.GOLD if active else "transparent")
            btn.configure(fg_color=t.SURFACE if active else "transparent",
                          text_color=t.TEXT if active else t.MUTED,
                          font=t.font(14, "bold" if active else "normal"))

    def set_nav_enabled(self, enabled: bool) -> None:
        for _bar, btn in self.nav_buttons.values():
            btn.configure(state="normal" if enabled else "disabled")

    # ----- shared folder -----
    def set_folder(self, folder: str) -> None:
        if self.worker.busy:
            return
        try:
            folder = self.guard.check_root(folder)
        except CleanerError as exc:
            self.current.status.show(str(exc), "error")
            return
        if os.path.normcase(folder) != os.path.normcase(self.folder):
            self.scan = None
        self.folder = folder
        self.settings["folder"] = folder
        for view in self.views.values():
            view.on_folder_changed(folder)
        self.current.status.show("")

    def contents_changed(self) -> None:
        """Files moved or were put back: the cached scan no longer matches the disk."""
        self.scan = None
        for view in self.views.values():
            view.on_contents_changed()

    def _dropped(self, event):
        items = self.tk.splitlist(event.data)
        if items and not self.worker.busy:
            p = Path(items[0])
            self.set_folder(str(p if p.is_dir() else p.parent))
        return event.action

    def _close(self) -> None:
        if self.worker.busy:
            if not widgets.confirm(self, "Stop and close?",
                                   "A job is still running. Stop it and close the app?",
                                   "Stop and close", danger=False,
                                   detail="Anything already moved stays in History, so you can undo it."):
                return
            self.worker.stop()
            self._close_when_idle()
            return
        self.settings.save()
        self.destroy()

    def _close_when_idle(self) -> None:
        if self.worker.busy:
            self.after(100, self._close_when_idle)
        else:
            self.settings.save()
            self.destroy()
