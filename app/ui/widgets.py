"""Reusable branded widgets: buttons, folder picker, tables, status line, dialogs."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from tkinter import filedialog, ttk
from typing import Callable

import customtkinter as ctk

from . import theme as t

try:
    from tkinterdnd2 import DND_FILES
except ImportError:  # drag-and-drop is optional; Choose always works
    DND_FILES = None

DND_READY = False  # flipped on by the window once tkdnd loads


def open_in_explorer(path: str | Path) -> None:
    path = Path(path)
    try:
        if sys.platform == "win32":
            if path.is_file():
                subprocess.run(["explorer", "/select,", str(path)])
            else:
                os.startfile(path)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.run(["open", "-R", str(path)])
        else:
            subprocess.run(["xdg-open", str(path.parent if path.is_file() else path)])
    except OSError:
        pass


def open_recycle_bin() -> None:
    if sys.platform == "win32":
        try:
            subprocess.Popen(["explorer", "shell:RecycleBinFolder"])
        except OSError:
            pass


def short_path(path: str, limit: int = 70) -> str:
    if len(path) <= limit:
        return path
    head, tail = path[: limit // 3], path[-(limit - limit // 3 - 1):]
    return head + "…" + tail


def plural(n: int, word: str, many: str | None = None) -> str:
    return f"{n:,} {word if n == 1 else (many or word + 's')}"


# ---------- buttons & text ----------
class PrimaryButton(ctk.CTkButton):
    """Gold call-to-action (or red for a destructive one). Looks clearly inactive when disabled."""

    def __init__(self, master, text: str, command: Callable, width: int = 0, danger: bool = False, **kw):
        self.color = t.DANGER if danger else t.GOLD
        super().__init__(master, text=text, command=command, height=42, corner_radius=t.RADIUS,
                         fg_color=self.color, hover_color=t.DANGER_HOVER if danger else t.GOLD_HOVER,
                         text_color=t.ON_GOLD, text_color_disabled=t.FAINT, font=t.font(14, "bold"),
                         width=width or 140, **kw)

    def set_enabled(self, on: bool, text: str | None = None) -> None:
        kw = {"text": text} if text else {}
        self.configure(state="normal" if on else "disabled",
                       fg_color=self.color if on else t.SURFACE_2, **kw)


def primary_button(master, text: str, command: Callable, width: int = 0, **kw) -> PrimaryButton:
    return PrimaryButton(master, text, command, width, **kw)


def ghost_button(master, text: str, command: Callable, width: int = 0, **kw) -> ctk.CTkButton:
    return ctk.CTkButton(
        master, text=text, command=command, height=34, corner_radius=8,
        fg_color="transparent", hover_color=t.SURFACE_2, border_width=1,
        border_color=t.BORDER_STRONG, text_color=t.TEXT, text_color_disabled=t.FAINT,
        font=t.font(13), width=width or 90, **kw)


def section_label(master, text: str) -> ctk.CTkLabel:
    return ctk.CTkLabel(master, text=text.upper(), font=t.font(11, "bold"),
                        text_color=t.FAINT, anchor="w")


def card(master, **kw) -> ctk.CTkFrame:
    return ctk.CTkFrame(master, fg_color=t.SURFACE, corner_radius=12,
                        border_width=1, border_color=t.BORDER, **kw)


def segmented(master, values: list[str], command: Callable | None = None, **kw) -> ctk.CTkSegmentedButton:
    return ctk.CTkSegmentedButton(
        master, values=values, command=command, height=34, corner_radius=8,
        fg_color=t.SURFACE_2, selected_color=t.GOLD, selected_hover_color=t.GOLD_HOVER,
        unselected_color=t.SURFACE_2, unselected_hover_color=t.BORDER_STRONG,
        text_color=t.TEXT, font=t.font(12, "bold"), **kw)


def entry(master, placeholder: str = "", width: int = 200, **kw) -> ctk.CTkEntry:
    return ctk.CTkEntry(
        master, placeholder_text=placeholder, width=width, height=34, corner_radius=8,
        fg_color=t.SURFACE_2, border_color=t.BORDER_STRONG, border_width=1,
        text_color=t.TEXT, placeholder_text_color=t.FAINT, font=t.font(13), **kw)


def option_menu(master, values: list[str], command: Callable | None = None, width: int = 150,
                **kw) -> ctk.CTkOptionMenu:
    return ctk.CTkOptionMenu(
        master, values=values, command=command, width=width, height=34, corner_radius=8,
        fg_color=t.SURFACE_2, button_color=t.SURFACE_2, button_hover_color=t.BORDER_STRONG,
        dropdown_fg_color=t.SURFACE_2, dropdown_hover_color=t.BORDER_STRONG,
        dropdown_text_color=t.TEXT, text_color=t.TEXT, font=t.font(13),
        dropdown_font=t.font(13), **kw)


def hint(master, text: str, **kw) -> ctk.CTkLabel:
    return ctk.CTkLabel(master, text=text, font=t.font(12), text_color=t.MUTED,
                        anchor="w", justify="left", **kw)


def size_bar(fraction: float, width: int = 14) -> str:
    filled = max(0, min(width, round(fraction * width)))
    if fraction > 0 and filled == 0:
        filled = 1
    return t.BAR_FULL * filled + t.BAR_EMPTY * (width - filled)


# ---------- folder picker ----------
class FolderField(ctk.CTkFrame):
    """One-line folder picker: click Choose, or drop a folder from Explorer anywhere on it."""

    def __init__(self, master, app, on_pick: Callable[[str], None]):
        super().__init__(master, height=64, fg_color=t.SURFACE, corner_radius=12,
                         border_width=2, border_color=t.BORDER_STRONG)
        self.app, self.on_pick = app, on_pick
        self.grid_propagate(False)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure((0, 3), weight=1)
        ctk.CTkLabel(self, text="DIR", width=42, height=32, corner_radius=7, fg_color=t.GOLD_SOFT,
                     text_color=t.GOLD, font=t.font(11, "bold")).grid(row=1, column=0, rowspan=2,
                                                                      padx=(14, 12))
        self.title = ctk.CTkLabel(self, text="", font=t.font(14, "bold"), text_color=t.TEXT, anchor="w")
        self.title.grid(row=1, column=1, sticky="sw")
        self.sub = ctk.CTkLabel(self, text="", font=t.font(12), text_color=t.MUTED, anchor="w")
        self.sub.grid(row=2, column=1, sticky="nw")
        self.button = ghost_button(self, "Choose folder", self.browse, width=120)
        self.button.grid(row=1, column=2, rowspan=2, padx=14)
        self.set_folder(app.folder)

        for widget in (self, self.title, self.sub):
            if DND_READY and DND_FILES:
                widget.drop_target_register(DND_FILES)
                widget.dnd_bind("<<Drop>>", self._dropped)
                widget.dnd_bind("<<DropEnter>>", lambda e: (self._hover(True), e.action)[1])
                widget.dnd_bind("<<DropLeave>>", lambda e: (self._hover(False), e.action)[1])

    def set_folder(self, folder: str) -> None:
        if folder:
            name = os.path.basename(folder.rstrip("\\/")) or folder
            self.title.configure(text=name)
            self.sub.configure(text=short_path(folder, 90))
            self.button.configure(text="Change")
        else:
            self.title.configure(text="Drop a folder here" if DND_READY else "Choose a folder")
            self.sub.configure(text="For example Downloads, Documents or an old backup drive folder")
            self.button.configure(text="Choose folder")

    def set_enabled(self, on: bool) -> None:
        self.button.configure(state="normal" if on else "disabled")

    def _hover(self, on: bool) -> None:
        self.configure(border_color=t.GOLD if on else t.BORDER_STRONG,
                       fg_color=t.SURFACE_2 if on else t.SURFACE)

    def browse(self) -> None:
        start = self.app.folder or str(Path.home() / "Downloads")
        picked = filedialog.askdirectory(initialdir=start, mustexist=True,
                                         title="Choose a folder to clean")
        if picked:
            self.on_pick(os.path.normpath(picked))

    def _dropped(self, event):
        self._hover(False)
        if self.app.worker.busy:
            return event.action
        items = self.tk.splitlist(event.data)
        if items:
            p = Path(items[0])
            self.on_pick(str(p if p.is_dir() else p.parent))
        return event.action


# ---------- tables ----------
class Table(ctk.CTkFrame):
    """A dark ttk.Treeview with a CustomTkinter scrollbar. Fast for thousands of rows."""

    def __init__(self, master, columns: list[tuple], tree_column: tuple | None = None,
                 selectmode: str = "extended", height: int = 10):
        """columns: (key, heading, width, anchor[, stretch]). Widths are at 100% display scaling.
        Stretchy columns share any spare width; by default that's the wide left-aligned ones."""
        super().__init__(master, fg_color=t.SURFACE, corner_radius=12, border_width=1,
                         border_color=t.BORDER)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
        show = "tree headings" if tree_column else "headings"
        self.tree = ttk.Treeview(self, columns=[c[0] for c in columns], show=show,
                                 selectmode=selectmode, style="Cleaner.Treeview", height=height)
        if tree_column:
            self.tree.heading("#0", text=tree_column[0], anchor="w")
            self.tree.column("#0", width=tree_column[1], minwidth=40, stretch=False)
        scale = ctk.ScalingTracker.get_widget_scaling(master)
        for key, heading, width, anchor, *rest in columns:
            stretch = rest[0] if rest else width >= 200
            self.tree.heading(key, text=heading, anchor=anchor)
            self.tree.column(key, width=int(width * scale), minwidth=int(36 * scale), anchor=anchor,
                             stretch=stretch)
        for tag, opts in t.TAGS.items():
            self.tree.tag_configure(tag, **opts)
        self.tree.grid(row=0, column=0, sticky="nsew", padx=(6, 0), pady=6)
        bar = ctk.CTkScrollbar(self, command=self.tree.yview, fg_color="transparent",
                               button_color=t.BORDER_STRONG, button_hover_color=t.FAINT)
        bar.grid(row=0, column=1, sticky="ns", padx=(2, 4), pady=6)
        self.tree.configure(yscrollcommand=bar.set)

        self.empty = ctk.CTkLabel(self, text="", font=t.font(13), text_color=t.FAINT)

    def clear(self) -> None:
        self.tree.delete(*self.tree.get_children())

    def show_empty(self, text: str) -> None:
        if text:
            self.empty.configure(text=text)
            self.empty.place(relx=0.5, rely=0.5, anchor="center")
        else:
            self.empty.place_forget()


# ---------- status line ----------
class StatusLine(ctk.CTkFrame):
    COLORS = {"info": t.MUTED, "ok": t.SUCCESS, "warn": t.WARNING, "error": t.DANGER, "busy": t.BLUE}

    def __init__(self, master):
        super().__init__(master, fg_color="transparent")
        self.grid_columnconfigure(1, weight=1)
        self.dot = ctk.CTkLabel(self, text="", font=t.font(11), text_color=t.FAINT, width=14)
        self.dot.grid(row=0, column=0, padx=(0, 6))
        self.label = ctk.CTkLabel(self, text="", font=t.font(12), text_color=t.MUTED,
                                  anchor="w", justify="left", wraplength=560)
        self.label.grid(row=0, column=1, sticky="ew")
        self.actions: list[ctk.CTkButton] = []

    def show(self, text: str, kind: str = "info",
             actions: list[tuple[str, Callable]] | None = None) -> None:
        color = self.COLORS.get(kind, t.MUTED)
        self.dot.configure(text_color=color, text="●" if text else "")
        self.label.configure(text=text, text_color=t.TEXT if kind in ("ok", "error") else t.MUTED)
        for b in self.actions:
            b.destroy()
        self.actions = []
        for i, (label, command) in enumerate(actions or []):
            b = ghost_button(self, label, command, width=0)
            b.configure(width=max(80, 9 * len(label) + 24))
            b.grid(row=0, column=2 + i, padx=(10, 0))
            self.actions.append(b)


# ---------- dialogs ----------
class _Dialog(ctk.CTkToplevel):
    def __init__(self, parent, title: str, width: int = 460):
        super().__init__(parent, fg_color=t.BG)
        self.withdraw()
        self.title(title)
        self.resizable(False, False)
        self.transient(parent.winfo_toplevel())
        self.result = False
        self.body = ctk.CTkFrame(self, fg_color="transparent", width=width)
        self.body.pack(fill="both", expand=True, padx=26, pady=22)
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.bind("<Escape>", lambda _e: self._cancel())

    def _show(self, parent) -> None:
        self.update_idletasks()
        top = parent.winfo_toplevel()
        x = top.winfo_rootx() + (top.winfo_width() - self.winfo_width()) // 2
        y = top.winfo_rooty() + (top.winfo_height() - self.winfo_height()) // 3
        self.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        self.deiconify()
        self.lift()
        self.after(50, self.focus_force)
        self.grab_set()
        self.wait_window()

    def _ok(self) -> None:
        self.result = True
        self.destroy()

    def _cancel(self) -> None:
        self.result = False
        self.destroy()


def confirm(parent, title: str, message: str, ok_text: str, danger: bool = True,
            detail: str = "") -> bool:
    """Modal yes/no. Returns True only if the user clicks the confirm button."""
    d = _Dialog(parent, title)
    ctk.CTkLabel(d.body, text=title, font=t.font(18, "bold"), text_color=t.TEXT,
                 anchor="w").pack(fill="x")
    ctk.CTkLabel(d.body, text=message, font=t.font(13), text_color=t.TEXT, anchor="w",
                 justify="left", wraplength=420).pack(fill="x", pady=(10, 0))
    if detail:
        ctk.CTkLabel(d.body, text=detail, font=t.font(12), text_color=t.MUTED, anchor="w",
                     justify="left", wraplength=420).pack(fill="x", pady=(8, 0))
    row = ctk.CTkFrame(d.body, fg_color="transparent")
    row.pack(fill="x", pady=(22, 0))
    ok = PrimaryButton(row, ok_text, d._ok, width=170, danger=danger)
    ok.pack(side="right")
    ghost_button(row, "Cancel", d._cancel, width=96).pack(side="right", padx=(0, 10))
    d.bind("<Return>", lambda _e: d._ok())
    d._show(parent)
    return d.result


def show_list(parent, title: str, message: str, rows: list[tuple[str, str]]) -> None:
    """Read-only list of (path, reason), e.g. files that were skipped."""
    d = _Dialog(parent, title, width=640)
    ctk.CTkLabel(d.body, text=title, font=t.font(18, "bold"), text_color=t.TEXT,
                 anchor="w").pack(fill="x")
    ctk.CTkLabel(d.body, text=message, font=t.font(13), text_color=t.MUTED, anchor="w",
                 justify="left", wraplength=600).pack(fill="x", pady=(6, 12))
    box = ctk.CTkTextbox(d.body, width=620, height=280, fg_color=t.SURFACE, text_color=t.TEXT,
                         font=t.font(12), border_width=1, border_color=t.BORDER, wrap="word")
    box.pack(fill="both", expand=True)
    for path, reason in rows:
        box.insert("end", f"{path}\n    {reason}\n\n")
    box.configure(state="disabled")
    row = ctk.CTkFrame(d.body, fg_color="transparent")
    row.pack(fill="x", pady=(16, 0))
    PrimaryButton(row, "Close", d._cancel, width=110).pack(side="right")
    d._show(parent)
