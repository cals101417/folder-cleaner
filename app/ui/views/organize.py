"""Organize: sort loose files into Images/, Documents/... or YYYY-MM/ folders. Preview first."""

from __future__ import annotations

import os

import customtkinter as ctk

from .. import theme as t
from ..widgets import Table, confirm, ghost_button, hint, open_in_explorer, plural, primary_button, \
    segmented, show_list
from ..worker import Throttle
from .base import ToolView
from ...core import organize, sizes

MODE_LABELS = organize.MODES   # {"type": "By type", "date": "By month"}


class OrganizeView(ToolView):
    title = "Organize"
    subtitle = ("Sort the loose files in a messy folder (like Downloads) into tidy subfolders. "
                "You see the plan before anything moves.")

    def build(self) -> None:
        self.plan: organize.Plan | None = None
        self.pending_status = None
        self._sorted: list[organize.Move] = []
        b = self.body
        b.grid_columnconfigure(0, weight=1)
        b.grid_rowconfigure(2, weight=1)

        bar = ctk.CTkFrame(b, fg_color="transparent")
        bar.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        bar.grid_columnconfigure(2, weight=1)
        self.mode = segmented(bar, list(MODE_LABELS.values()), command=lambda _v: self._mode_changed())
        self.mode.set(MODE_LABELS.get(self.settings.get("organize_mode"), MODE_LABELS["type"]))
        self.mode.grid(row=0, column=0, sticky="w")
        self.mode_hint = hint(bar, "")
        self.mode_hint.grid(row=0, column=1, sticky="w", padx=(14, 0))
        self.skipped_btn = ghost_button(bar, "Staying put", self._show_skipped, width=130)

        self.chips = ctk.CTkFrame(b, fg_color="transparent")
        self.chips.grid(row=1, column=0, sticky="ew", pady=(0, 10))

        self.table = Table(b, [("name", "File", 300, "w"), ("arrow", "", 40, "center"),
                               ("dst", "Moves to", 300, "w"), ("size", "Size", 90, "e"),
                               ("note", "", 170, "w")], selectmode="browse")
        self.table.grid(row=2, column=0, sticky="nsew")
        self.table.tree.bind("<Double-1>", self._open)
        hint(b, "Only files sitting directly in this folder move. Subfolders stay as they are. "
                "A name that's already taken gets “ (2)” added, so nothing is overwritten."
             ).grid(row=3, column=0, sticky="w", pady=(8, 0))

        self.move_btn = primary_button(self.footer, "Move files", self.apply, width=190)
        self.preview_btn = ghost_button(self.footer, "Preview again", self.preview, width=130)
        self._mode_hint()
        self._empty()

    def _mode_key(self) -> str:
        label = self.mode.get()
        return next(k for k, v in MODE_LABELS.items() if v == label)

    def _mode_hint(self) -> None:
        self.mode_hint.configure(
            text="Images, Documents, Archives, Installers, Video, Audio, Other"
            if self._mode_key() == "type" else "One folder per month, like 2026-10, by date modified")

    def _mode_changed(self) -> None:
        self.settings["organize_mode"] = self._mode_key()
        self._mode_hint()
        if self.app.folder:
            self.preview()

    def on_show(self) -> None:
        if self.app.folder and self.plan is None and not self.worker.busy:
            self.preview()

    def on_folder_changed(self, folder: str) -> None:
        super().on_folder_changed(folder)
        self.plan = None
        if self.app.current is self:
            self.preview()
        else:
            self._empty()

    def _empty(self) -> None:
        self.table.clear()
        self.table.show_empty("Pick a folder to see how it would be sorted.")
        for w in self.chips.winfo_children():
            w.destroy()
        self.move_btn.grid_remove()
        self.preview_btn.grid_remove()
        self.skipped_btn.grid_remove()

    # ----- preview (dry run) -----
    def preview(self) -> None:
        if not self.app.folder or self.worker.busy:
            return
        folder, mode = self.app.folder, self._mode_key()
        self.set_busy(True, "Working out where everything goes…", cancellable=False)
        self.worker.run(lambda: organize.plan(folder, mode, guard=self.app.guard),
                        self._planned, self._plan_failed)

    def _plan_failed(self, message: str) -> None:
        self.failed(message)
        self._empty()

    def _planned(self, plan: organize.Plan) -> None:
        self.set_busy(False)
        self.plan = plan
        tree = self.table.tree
        self.table.clear()
        self._sorted = sorted(plan.moves, key=lambda m: (m.folder.lower(), m.rec.name.lower()))
        for i, m in enumerate(self._sorted):
            rel = os.path.relpath(m.dst, plan.root)
            tree.insert("", "end", iid=str(i), values=(
                m.rec.name, "→", rel, sizes.human_size(m.rec.size),
                "renamed to avoid a clash" if m.renamed else ""), tags=("warn",) if m.renamed else ())

        for w in self.chips.winfo_children():
            w.destroy()
        for folder, n in sorted(plan.counts().items()):
            chip = ctk.CTkLabel(self.chips, text=f"{folder}  {n}", font=t.font(12, "bold"),
                                fg_color=t.SURFACE_2, corner_radius=8, text_color=t.TEXT, height=28)
            chip.pack(side="left", padx=(0, 8), ipadx=10)

        n = len(plan.moves)
        if plan.skipped:
            self.skipped_btn.configure(text=f"{len(plan.skipped):,} staying put")
            self.skipped_btn.grid(row=0, column=3, sticky="e")
        else:
            self.skipped_btn.grid_remove()
        self.preview_btn.grid(row=0, column=2, padx=(12, 0))
        if n:
            self.table.show_empty("")
            self.move_btn.grid(row=0, column=3, padx=(12, 0))
            self.move_btn.set_enabled(True, f"Move {plural(n, 'file')}")
            self.status.show(f"Preview: {plural(n, 'file')} ({sizes.human_size(plan.total_bytes)}) "
                             f"would move into {plural(len(plan.counts()), 'folder')}. "
                             "Nothing has moved yet.", "info")
        else:
            self.table.show_empty("Nothing to sort. There are no loose files in this folder.")
            self.move_btn.grid_remove()
            self.status.show("")
        if self.pending_status:
            self.status.show(*self.pending_status)
            self.pending_status = None

    def _show_skipped(self) -> None:
        if self.plan and self.plan.skipped:
            show_list(self, "Staying put", "These files won't be moved.", self.plan.skipped)

    def _open(self, event) -> None:
        row = self.table.tree.identify_row(event.y)
        if row and self.plan:
            open_in_explorer(self._sorted[int(row)].rec.path)

    # ----- apply -----
    def apply(self) -> None:
        p = self.plan
        if not p or not p.moves or self.worker.busy:
            return
        if not confirm(self, "Move these files?",
                       f"{plural(len(p.moves), 'file')} ({sizes.human_size(p.total_bytes)}) will move into "
                       f"{plural(len(p.counts()), 'folder')} inside {os.path.basename(p.root)}.",
                       f"Move {plural(len(p.moves), 'file')}", danger=False,
                       detail="Nothing is deleted or overwritten. You can undo this from History."):
            return
        self.set_busy(True, "Moving files…")
        progress = Throttle(self.worker, self._action_progress)
        self.worker.run(lambda: organize.apply(p, guard=self.app.guard, journal=self.app.journal,
                                               progress=progress, cancel=self.worker.cancel),
                        self._moved, self.failed)

    def _action_progress(self, p) -> None:
        if self.worker.busy:
            self.set_progress(p.done / max(p.total, 1))
            self.status.show(f"Moving {p.done + 1:,} of {p.total:,}  ·  {os.path.basename(p.path)}", "busy")

    def _moved(self, report) -> None:
        self.set_busy(False)
        self.app.contents_changed()
        root = self.plan.root
        text, kind = self.describe_report(report, "Moved")
        acts = [("Undo", lambda: self.undo_batch(report.batch_id)),
                ("Open folder", lambda: open_in_explorer(root))]
        skipped = self.skipped_action(report)
        if skipped:
            acts.insert(0, skipped)
        self.plan = None
        self.pending_status = (text, kind, acts)   # shown once the fresh preview is in
        self.preview()

    def show_undo_result(self, text: str, kind: str, acts: list) -> None:
        self.plan = None
        self.pending_status = (text, kind, acts)
        self.preview()

    def on_contents_changed(self) -> None:
        if self.app.current is not self:
            self.plan = None
