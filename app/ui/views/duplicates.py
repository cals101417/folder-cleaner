"""Duplicates: exact copies grouped together. One copy per group always stays."""

from __future__ import annotations

import os
import time

import customtkinter as ctk

from .. import theme as t
from ..widgets import (Table, confirm, hint, open_in_explorer, option_menu, plural, primary_button,
                       segmented, show_list)
from ..worker import Throttle
from .base import ToolView
from ...core import actions, dupes, sizes
from ...core.errors import CleanerError
from ...core.scan import scan

MAX_GROUPS = 2000          # keep the table snappy; groups are sorted by space wasted
KEEP_LABELS = {k: label for k, (label, _key) in dupes.KEEP_POLICIES.items()}
RECYCLE_MARK, KEEP_MARK = "✕  Recycle", "✓  Keep"
# Tiny duplicates are rarely worth the risk or the clicks; 1 MB keeps the list to real waste.
MIN_SIZES = {"100 KB": 100 * 1024, "1 MB": 1024 ** 2, "10 MB": 10 * 1024 ** 2, "Any size": 1}
DEFAULT_MIN = "1 MB"


class DuplicatesView(ToolView):
    title = "Duplicates"
    subtitle = "Find exact copies (same content, not just the same name). One copy of each always stays."

    def build(self) -> None:
        self.groups: list[dupes.DupeGroup] = []
        self.marks: set[str] = set()
        self.row_file: dict[str, tuple[int, object]] = {}   # iid -> (group index, record)
        self.result = None

        b = self.body
        b.grid_columnconfigure(0, weight=1)
        b.grid_rowconfigure(1, weight=1)

        bar = ctk.CTkFrame(b, fg_color="transparent")
        bar.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        bar.grid_columnconfigure(1, weight=1)
        self.policy = segmented(bar, list(KEEP_LABELS.values()), command=self._policy_changed)
        self.policy.set(KEEP_LABELS.get(self.settings.get("keep_policy"), KEEP_LABELS["oldest"]))
        self.policy.grid(row=0, column=0, sticky="w")
        hint(bar, "Files bigger than").grid(row=0, column=1, sticky="e", padx=(18, 6))
        self.min_size = option_menu(bar, list(MIN_SIZES), self._min_size_changed, width=100)
        saved = self.settings.get("dupe_min_size")
        self.min_size.set(saved if saved in MIN_SIZES else DEFAULT_MIN)
        self.min_size.grid(row=0, column=2, sticky="w")
        bar.grid_columnconfigure(1, weight=0)
        bar.grid_columnconfigure(3, weight=1)
        self.summary = ctk.CTkLabel(bar, text="", font=t.font(13), text_color=t.MUTED, anchor="e")
        self.summary.grid(row=0, column=3, sticky="e")

        self.table = Table(b, [("mark", "", 100, "w"), ("name", "File", 260, "w"),
                               ("folder", "Folder", 260, "w"), ("date", "Modified", 130, "w"),
                               ("size", "Size", 90, "e")], selectmode="browse")
        self.table.grid(row=1, column=0, sticky="nsew")
        self.table.tree.bind("<Button-1>", self._clicked, add="+")
        self.table.tree.bind("<space>", self._toggle_selected)
        self.table.tree.bind("<Double-1>", self._open)
        hint(b, "Click Keep / Recycle to switch a copy. Double-click a file to see it in Explorer. "
                "Code projects (repos, node_modules, venvs) are never searched, so nothing in them breaks."
             ).grid(row=2, column=0, sticky="w", pady=(8, 0))

        self.recycle_btn = primary_button(self.footer, "Recycle", self.recycle, width=220, danger=True)
        self.find_btn = primary_button(self.footer, "Find duplicates", self.start, width=170)
        self.find_btn.grid(row=0, column=4, padx=(12, 0))
        self._empty()

    def on_show(self) -> None:
        self.find_btn.set_enabled(bool(self.app.folder))

    def on_folder_changed(self, folder: str) -> None:
        super().on_folder_changed(folder)
        if self.result is not None and self.app.scan is None:
            self._empty()
        self.find_btn.set_enabled(bool(folder))

    def on_contents_changed(self) -> None:
        self._empty()

    def _empty(self) -> None:
        self.result, self.groups, self.marks = None, [], set()
        self.table.clear()
        self.table.show_empty("Pick a folder, then press Find duplicates." if not self.app.folder
                              else "Press Find duplicates to compare the files in this folder.")
        self.summary.configure(text="")
        self.recycle_btn.grid_remove()

    # ----- search -----
    def start(self) -> None:
        if not self.app.folder or self.worker.busy:
            return
        folder, cached = self.app.folder, self.app.scan
        self.set_busy(True, "Listing files…")
        self.find_btn.set_enabled(False)
        progress = Throttle(self.worker, self._progress, 0.15)
        cancel = self.worker.cancel
        min_size = MIN_SIZES[self.min_size.get()]

        def job():
            result = cached if cached is not None and cached.root == folder else \
                scan(folder, guard=self.app.guard, cancel=cancel)
            return result, dupes.find_duplicates(result.files, min_size=min_size, progress=progress,
                                                 cancel=cancel)

        self.worker.run(job, self._found, self._failed, self._cancelled)

    def _progress(self, p) -> None:
        if not self.worker.busy:
            return
        if p.stage == "quick":
            self.status.show(f"Comparing the start of each file…  {p.done:,} of {p.total:,}", "busy")
        else:
            self.status.show(f"Confirming matches byte by byte…  {sizes.human_size(p.done)} of "
                             f"{sizes.human_size(p.total)}", "busy")
        self.set_progress(p.done / max(p.total, 1))

    def _failed(self, message: str) -> None:
        self.failed(message)
        self.find_btn.set_enabled(bool(self.app.folder))

    def _cancelled(self, message: str) -> None:
        self.cancelled(message)
        self.find_btn.set_enabled(bool(self.app.folder))

    def _found(self, value) -> None:
        scan_result, result = value
        self.set_busy(False)
        self.find_btn.set_enabled(True, "Search again")
        self.app.scan = scan_result
        self.result = result
        self._show_groups()
        self._report()

    def _report(self) -> None:
        result, scan_result = self.result, self.app.scan
        groups = self._visible_groups()
        if not groups:
            text = "No duplicates found."
        else:
            text = (f"{plural(len(groups), 'group')} of copies, "
                    f"{sizes.human_size(sum(g.wasted for g in groups))} could be freed.")
            if len(groups) > MAX_GROUPS:
                text = f"{text[:-1]} (showing the {MAX_GROUPS:,} biggest)."
        left_out = len(scan_result.projects) + len(result.skipped) + (1 if result.online_only else 0)
        if not left_out:
            acts = []
        elif scan_result.projects:
            acts = [(f"{plural(len(scan_result.projects), 'code project')} left out", self._show_left_out)]
        else:
            acts = [("What was left out", self._show_left_out)]
        self.status.show(text, "ok", acts)

    def _show_left_out(self) -> None:
        result, scan_result = self.result, self.app.scan
        if result is None or scan_result is None:
            return
        rows = [(p.root, f"Not searched: {p.describe()}. Every project needs its own copy of these "
                         "files, so recycling one would break it.")
                for p in sorted(scan_result.projects.values(), key=lambda p: p.root.lower())]
        rows += [(path, f"Couldn't be read: {why}") for path, why in result.skipped]
        if result.online_only:
            rows.append(("OneDrive / cloud files", f"{plural(result.online_only, 'online-only file')} "
                         "skipped, so nothing gets downloaded."))
        note = "These weren't compared. Nothing happened to them."
        if result.min_size > 1:
            note += (f" Files under {sizes.human_size(result.min_size)} were also ignored "
                     f"({plural(result.too_small, 'file')}).")
        show_list(self, "Left out of the search", note, rows[:3000])

    def _visible_groups(self) -> list:
        limit = MIN_SIZES[self.min_size.get()]
        return [g for g in self.result.groups if g.size >= limit] if self.result else []

    def _show_groups(self) -> None:
        self.groups = self._visible_groups()[:MAX_GROUPS]
        self.marks = dupes.default_marks(self.groups, self._policy_key())
        self._fill()

    def _min_size_changed(self, label: str) -> None:
        self.settings["dupe_min_size"] = label
        if self.result is None:
            return
        if MIN_SIZES[label] >= self.result.min_size:   # stricter limit: filter what we already have
            self._show_groups()
            self._report()
        else:
            self._empty()
            self.status.show(f"Press Find duplicates to include files down to {label}.", "info")

    # ----- table -----
    def _policy_key(self) -> str:
        label = self.policy.get()
        return next(k for k, v in KEEP_LABELS.items() if v == label)

    def _policy_changed(self, _label) -> None:
        self.settings["keep_policy"] = self._policy_key()
        if self.groups:
            self.marks = dupes.default_marks(self.groups, self._policy_key())
            self._fill()

    def _fill(self) -> None:
        tree = self.table.tree
        self.table.clear()
        self.row_file.clear()
        root = self.app.scan.root if self.app.scan else ""
        for gi, g in enumerate(self.groups):
            gid = f"g{gi}"
            tree.insert("", "end", iid=gid, open=True, tags=("group",), values=(
                "", f"{len(g.files)} copies  ·  {sizes.human_size(g.size)} each", "", "",
                f"+{sizes.human_size(g.wasted)}"))
            for fi, rec in enumerate(g.files):
                iid = f"{gi}:{fi}"
                self.row_file[iid] = (gi, rec)
                tree.insert(gid, "end", iid=iid, values=(
                    "", rec.name, dupes.display_folder(rec.path, root),
                    time.strftime("%Y-%m-%d %H:%M", time.localtime(rec.mtime)),
                    sizes.human_size(rec.size)))
                self._paint(iid)
        self.table.show_empty("" if self.groups else "No duplicates found.")
        self._update_totals()

    def _paint(self, iid: str) -> None:
        _gi, rec = self.row_file[iid]
        marked = rec.path in self.marks
        self.table.tree.set(iid, "mark", RECYCLE_MARK if marked else KEEP_MARK)
        self.table.tree.item(iid, tags=("marked",) if marked else ("keep",))

    def _toggle(self, iid: str) -> None:
        if iid not in self.row_file:
            return
        gi, rec = self.row_file[iid]
        if rec.path in self.marks:
            self.marks.discard(rec.path)
        elif dupes.can_mark(self.groups[gi], self.marks, rec.path):
            self.marks.add(rec.path)
        else:
            self.status.show("Keep at least one copy in each group. Tick another copy to Keep "
                             "first if you want to recycle this one.", "warn")
            return
        self._paint(iid)
        self._update_totals()

    def _clicked(self, event) -> None:
        tree = self.table.tree
        if tree.identify_region(event.x, event.y) != "cell":
            return
        if tree.identify_column(event.x) == "#1":   # the Keep / Recycle column
            self._toggle(tree.identify_row(event.y))

    def _toggle_selected(self, _event=None) -> None:
        for iid in self.table.tree.selection():
            self._toggle(iid)

    def _open(self, event) -> None:
        iid = self.table.tree.identify_row(event.y)
        if iid in self.row_file and self.table.tree.identify_column(event.x) != "#1":
            open_in_explorer(self.row_file[iid][1].path)

    def _chosen(self):
        return dupes.selected_for_removal(self.groups, self.marks)

    def _update_totals(self) -> None:
        try:
            chosen = self._chosen()
        except CleanerError:
            chosen = []
        total = sum(r.size for r in chosen)
        if self.groups:
            self.summary.configure(text=f"{plural(len(self.groups), 'group')}  ·  "
                                        f"{plural(len(chosen), 'copy', 'copies')} marked  ·  "
                                        f"{sizes.human_size(total)}")
        if chosen:
            self.recycle_btn.grid(row=0, column=3, padx=(12, 0))
            self.recycle_btn.set_enabled(True, f"Recycle {len(chosen):,} ({sizes.human_size(total)})")
        else:
            self.recycle_btn.grid_remove()

    # ----- recycle -----
    def recycle(self) -> None:
        if self.worker.busy:
            return
        try:
            chosen = self._chosen()
        except CleanerError as exc:
            self.status.show(str(exc), "error")
            return
        if not chosen:
            return
        total = sum(r.size for r in chosen)
        if not confirm(self, "Recycle the duplicate copies?",
                       f"{plural(len(chosen), 'copy', 'copies')} ({sizes.human_size(total)}) will go "
                       "to the Recycle Bin. One copy of each file stays where it is.",
                       f"Recycle {plural(len(chosen), 'copy', 'copies')}",
                       detail="You can restore them from the Recycle Bin until it's emptied. "
                              "Any copy that changed since the search is skipped."):
            return
        self.set_busy(True, "Sending copies to the Recycle Bin…")
        progress = Throttle(self.worker, self._action_progress)
        root = self.app.scan.root
        self.worker.run(lambda: actions.recycle(chosen, label="Duplicates", root=root,
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
        gone = report.done_paths
        sizes.remove_files(self.app.scan, gone)
        overview = self.app.views.get("overview")
        if overview is not None and overview.tree is not None:
            overview._show_scan(self.app.scan, keep_place=True)
        # Drop recycled copies; groups left with one file are solved.
        for g in self.groups:
            g.files = [r for r in g.files if r.path not in gone]
        self.groups = [g for g in self.groups if len(g.files) > 1]
        self.marks -= gone
        self._fill()
        text, kind = self.describe_report(report, "Sent", " to the Recycle Bin")
        self.status.show(text, kind, [a for a in [self.skipped_action(report)] if a])
