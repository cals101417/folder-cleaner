"""Overview: what's taking up space. Largest files and folders, filters, send to Recycle Bin."""

from __future__ import annotations

import os
import time

import customtkinter as ctk

from .. import theme as t
from ..widgets import (Table, confirm, entry, ghost_button, hint, open_in_explorer, option_menu,
                       plural, primary_button, section_label, short_path, size_bar)
from ..worker import Throttle
from .base import ToolView
from ...core import actions, sizes
from ...core.errors import CleanerError
from ...core.rules import CATEGORY_NAMES, Filters, parse_filters
from ...core.scan import scan

ALL_TYPES = "All types"
SHOW_COUNTS = ["20", "100", "1000"]


def when(mtime: float) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(mtime))


class Stat(ctk.CTkFrame):
    def __init__(self, master, label: str):
        super().__init__(master, fg_color=t.SURFACE, corner_radius=12, border_width=1,
                         border_color=t.BORDER)
        self.value = ctk.CTkLabel(self, text="–", font=t.font(20, "bold"), text_color=t.TEXT, anchor="w")
        self.value.pack(fill="x", padx=16, pady=(12, 0))
        ctk.CTkLabel(self, text=label, font=t.font(12), text_color=t.MUTED,
                     anchor="w").pack(fill="x", padx=16, pady=(0, 12))


class OverviewView(ToolView):
    title = "Overview"
    subtitle = "See what's taking up space. Scanning only reads; nothing changes until you confirm."

    def build(self) -> None:
        self.tree = None
        self.here = ""            # folder the tables are showing (drill-down)
        self.filters = Filters()
        self.shown_files = []

        b = self.body
        b.grid_columnconfigure(0, weight=3)
        b.grid_columnconfigure(1, weight=2)
        b.grid_rowconfigure(3, weight=1)

        stats = ctk.CTkFrame(b, fg_color="transparent")
        stats.grid(row=0, column=0, columnspan=2, sticky="ew")
        self.stats = {}
        for i, (key, label) in enumerate([("size", "Total size"), ("files", "Files"),
                                          ("folders", "Folders"), ("skipped", "Skipped")]):
            stats.grid_columnconfigure(i, weight=1, uniform="stat")
            self.stats[key] = Stat(stats, label)
            self.stats[key].grid(row=0, column=i, sticky="ew", padx=(0 if i == 0 else 10, 0))

        # filter bar
        bar = ctk.CTkFrame(b, fg_color="transparent")
        bar.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(14, 10))
        hint(bar, "Bigger than").pack(side="left")
        self.min_mb = entry(bar, "MB", width=70)
        self.min_mb.pack(side="left", padx=(6, 14))
        hint(bar, "Older than").pack(side="left")
        self.months = entry(bar, "months", width=80)
        self.months.pack(side="left", padx=(6, 14))
        self.category = option_menu(bar, [ALL_TYPES] + CATEGORY_NAMES, width=130)
        self.category.pack(side="left", padx=(0, 10))
        ghost_button(bar, "Apply", self.apply_filters, width=70).pack(side="left")
        self.clear_btn = ghost_button(bar, "Clear", self.clear_filters, width=64)
        self.show_count = option_menu(bar, SHOW_COUNTS, lambda _v: self.refresh(), width=74)
        self.show_count.pack(side="right")
        hint(bar, "Show").pack(side="right", padx=(0, 6))
        for e in (self.min_mb, self.months):
            e.bind("<Return>", lambda _e: self.apply_filters())

        # headings
        left = ctk.CTkFrame(b, fg_color="transparent")
        left.grid(row=2, column=0, sticky="ew", pady=(0, 6), padx=(0, 12))
        left.grid_columnconfigure(0, weight=1)
        self.files_label = section_label(left, "Largest files")
        self.files_label.grid(row=0, column=0, sticky="w")
        right = ctk.CTkFrame(b, fg_color="transparent")
        right.grid(row=2, column=1, sticky="ew", pady=(0, 6))
        right.grid_columnconfigure(0, weight=1)
        self.folders_label = section_label(right, "Largest folders")
        self.folders_label.grid(row=0, column=0, sticky="w")
        self.up_btn = ghost_button(right, "↑ Up", self.go_up, width=60)

        self.files = Table(b, [("name", "File", 170, "w", True), ("size", "Size", 72, "e"),
                               ("bar", "", 84, "w"), ("date", "Modified", 84, "w"),
                               ("folder", "Folder", 110, "w", True)])
        self.files.grid(row=3, column=0, sticky="nsew", padx=(0, 12))
        self.files.tree.bind("<<TreeviewSelect>>", lambda _e: self._selection_changed())
        self.files.tree.bind("<Double-1>", self._open_file)
        self.folders = Table(b, [("name", "Folder", 140, "w", True), ("size", "Size", 72, "e"),
                                 ("bar", "", 70, "w"), ("count", "Files", 52, "e")],
                             selectmode="browse")
        self.folders.grid(row=3, column=1, sticky="nsew")
        self.folders.tree.bind("<Double-1>", self._drill)
        self.folders.tree.bind("<Return>", self._drill)
        hint(b, "Tip: double-click a folder to look inside it. Ctrl or Shift-click to pick several files."
             ).grid(row=4, column=0, columnspan=2, sticky="w", pady=(8, 0))

        self.recycle_btn = primary_button(self.footer, "Recycle", self.recycle, width=200, danger=True)
        self.reveal_btn = ghost_button(self.footer, "Show in folder", self._reveal_selected, width=120)
        self.scan_btn = primary_button(self.footer, "Scan folder", self.start, width=160)
        self.scan_btn.grid(row=0, column=4, padx=(12, 0))
        self._empty_state()

    # ----- scanning -----
    def on_show(self) -> None:
        if self.app.scan is not None and self.tree is None:
            self._show_scan(self.app.scan)
        self.scan_btn.set_enabled(bool(self.app.folder))

    def on_folder_changed(self, folder: str) -> None:
        super().on_folder_changed(folder)
        if self.app.scan is None:
            self.tree = None
            self._empty_state()
        self.scan_btn.set_enabled(bool(folder))

    def on_contents_changed(self) -> None:
        self.tree = None
        self._empty_state()
        self.files.show_empty("Files were moved. Press Scan folder to see the folder as it is now.")

    def start(self) -> None:
        if not self.app.folder or self.worker.busy:
            return
        folder = self.app.folder
        self.set_busy(True, "Scanning…")
        self.scan_btn.set_enabled(False)
        progress = Throttle(self.worker, self._progress)

        def job():
            result = scan(folder, guard=self.app.guard, progress=progress, cancel=self.worker.cancel)
            return result, sizes.build_tree(result)

        self.worker.run(job, self._scanned, self._scan_failed, self._scan_cancelled)

    def _progress(self, p) -> None:
        if self.worker.busy:
            self.status.show(f"Scanning…  {p.files:,} files  ·  {sizes.human_size(p.bytes)}  ·  "
                             f"{short_path(p.folder, 60)}", "busy")

    def _scanned(self, value) -> None:
        result, tree = value
        self.set_busy(False)
        self.scan_btn.set_enabled(True, "Scan again")
        self.app.scan = result
        self._show_scan(result, tree)
        n = len(result.skipped)
        took = "under a second" if result.seconds < 1 else f"{result.seconds:.0f} s"
        text = f"Scanned {plural(len(result.files), 'file')} in {took}."
        acts = []
        if n:
            text += f" {plural(n, 'item')} couldn't be read and {'was' if n == 1 else 'were'} skipped."
            acts.append(("See which", lambda: self._show_skipped(result)))
        self.status.show(text, "warn" if n else "ok", acts)

    def _scan_failed(self, message: str) -> None:
        self.failed(message)
        self.scan_btn.set_enabled(bool(self.app.folder))

    def _scan_cancelled(self, message: str) -> None:
        self.cancelled(message)
        self.scan_btn.set_enabled(bool(self.app.folder))

    def _show_skipped(self, result) -> None:
        from ..widgets import show_list
        show_list(self, "Skipped while scanning",
                  "These couldn't be read, so they aren't counted. Nothing happened to them.",
                  result.skipped[:2000])

    def _show_scan(self, result, tree=None, keep_place: bool = False) -> None:
        self.tree = tree or sizes.build_tree(result)
        if not (keep_place and self.here in self.tree.total):
            self.here = result.root
        self.stats["size"].value.configure(text=sizes.human_size(result.total_size))
        self.stats["files"].value.configure(text=f"{len(result.files):,}")
        self.stats["folders"].value.configure(text=f"{max(len(result.folders) - 1, 0):,}")
        skipped = len(result.skipped) + result.links_skipped + len(result.protected_skipped)
        self.stats["skipped"].value.configure(text=f"{skipped:,}")
        self.refresh()

    def _empty_state(self) -> None:
        for s in self.stats.values():
            s.value.configure(text="–")
        self.files.clear()
        self.folders.clear()
        self.files.show_empty("Pick a folder, then press Scan folder." if not self.app.folder
                              else "Press Scan folder to see what's inside.")
        self.folders.show_empty("")
        self.up_btn.grid_remove()
        self.recycle_btn.grid_remove()
        self.reveal_btn.grid_remove()
        self.files_label.configure(text="LARGEST FILES")

    # ----- tables -----
    def refresh(self) -> None:
        if self.tree is None or self.app.scan is None:
            return
        result = self.app.scan
        limit = int(self.show_count.get())
        match = self.filters.matcher() if self.filters.active else None
        under = None if self.here == result.root else self.here
        top = sizes.largest_files(result.files, limit, match, under)
        self.shown_files = top

        self.files.clear()
        biggest = top[0].size if top else 1
        for i, rec in enumerate(top):
            folder = os.path.relpath(rec.folder, result.root)
            self.files.tree.insert("", "end", iid=str(i), values=(
                rec.name, sizes.human_size(rec.size), size_bar(rec.size / biggest),
                when(rec.mtime), "(top folder)" if folder == "." else folder))
        where = "" if under is None else f" in {os.path.basename(self.here)}"
        title = f"Largest files{where}"
        if self.filters.active:
            matching = [f for f in result.files if match(f) and (under is None or
                        f.path.startswith(under + os.sep))]
            title = (f"{plural(len(matching), 'matching file')}{where}  ·  "
                     f"{sizes.human_size(sum(f.size for f in matching))}")
            self.clear_btn.pack(side="left", padx=(6, 0))
        else:
            self.clear_btn.pack_forget()
        self.files_label.configure(text=title.upper())
        self.files.show_empty("" if top else ("No files match these filters." if match else
                                              "No files here."))

        self.folders.clear()
        kids = sizes.largest_folders(self.tree, self.here, 200)
        top_size = kids[0][1] if kids and kids[0][1] else 1
        for path, size, count in kids:
            self.folders.tree.insert("", "end", iid=path, values=(
                os.path.basename(path), sizes.human_size(size), size_bar(size / top_size), f"{count:,}"))
        self.folders.show_empty("" if kids else "No subfolders.")
        here_name = os.path.basename(self.here) or self.here
        self.folders_label.configure(text=f"Largest folders in {here_name}".upper())
        if self.here != result.root:
            self.up_btn.grid(row=0, column=1)
        else:
            self.up_btn.grid_remove()
        self._selection_changed()

    def apply_filters(self) -> None:
        try:
            cat = self.category.get()
            self.filters = parse_filters(self.min_mb.get(), self.months.get(),
                                         None if cat == ALL_TYPES else cat)
        except CleanerError as exc:
            self.status.show(str(exc), "error")
            return
        self.status.show("")
        self.refresh()

    def clear_filters(self) -> None:
        self.min_mb.delete(0, "end")
        self.months.delete(0, "end")
        self.category.set(ALL_TYPES)
        self.filters = Filters()
        self.refresh()

    def _drill(self, _event=None) -> None:
        sel = self.folders.tree.selection()
        if sel:
            self.here = sel[0]
            self.refresh()

    def go_up(self) -> None:
        if self.app.scan and self.here != self.app.scan.root:
            self.here = os.path.dirname(self.here)
            self.refresh()

    def _selected(self):
        return [self.shown_files[int(i)] for i in self.files.tree.selection()]

    def _selection_changed(self) -> None:
        chosen = self._selected()
        if chosen:
            total = sum(r.size for r in chosen)
            self.recycle_btn.grid(row=0, column=3, padx=(12, 0))
            self.recycle_btn.set_enabled(True, f"Recycle {len(chosen)} ({sizes.human_size(total)})")
            self.reveal_btn.grid(row=0, column=2, padx=(12, 0))
        else:
            self.recycle_btn.grid_remove()
            self.reveal_btn.grid_remove()

    def _open_file(self, event) -> None:
        row = self.files.tree.identify_row(event.y)
        if row:
            open_in_explorer(self.shown_files[int(row)].path)

    def _reveal_selected(self) -> None:
        chosen = self._selected()
        if chosen:
            open_in_explorer(chosen[0].path)

    # ----- recycle -----
    def recycle(self) -> None:
        chosen = self._selected()
        if not chosen or self.worker.busy:
            return
        total = sum(r.size for r in chosen)
        if not confirm(self, "Send to the Recycle Bin?",
                       f"{plural(len(chosen), 'file')} ({sizes.human_size(total)}) will go to the "
                       "Recycle Bin.",
                       f"Recycle {plural(len(chosen), 'file')}",
                       detail="You can restore them from the Recycle Bin until it's emptied. "
                              "Files that changed since the scan are skipped."):
            return
        self.set_busy(True, "Sending files to the Recycle Bin…")
        progress = Throttle(self.worker, self._action_progress)
        root = self.app.scan.root
        self.worker.run(lambda: actions.recycle(chosen, label="Overview", root=root,
                                                guard=self.app.guard, journal=self.app.journal,
                                                progress=progress, cancel=self.worker.cancel),
                        self._recycled, self.failed)

    def _action_progress(self, p) -> None:
        if self.worker.busy:
            self.set_progress(p.done / max(p.total, 1))
            self.status.show(f"Recycling {p.done + 1:,} of {p.total:,}  ·  {os.path.basename(p.path)}",
                             "busy")

    def _recycled(self, report) -> None:
        self.set_busy(False)
        sizes.remove_files(self.app.scan, report.done_paths)
        self._show_scan(self.app.scan, keep_place=True)
        text, kind = self.describe_report(report, "Sent", " to the Recycle Bin")
        self.status.show(text, kind, [a for a in [self.skipped_action(report)] if a])
