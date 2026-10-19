"""History & undo: every batch the app ran. Moves can be undone; recycled files are restored
from the Recycle Bin itself."""

from __future__ import annotations

import os
from datetime import datetime

import customtkinter as ctk

from ..widgets import Table, ghost_button, hint, open_in_explorer, open_recycle_bin, plural, \
    primary_button, section_label, short_path
from .base import ToolView
from ...core.actions import RECYCLE_UNDO_HELP
from ...core.sizes import human_size


def nice_time(iso: str) -> str:
    try:
        when = datetime.fromisoformat(iso)
    except ValueError:
        return iso
    today = datetime.now().date()
    if when.date() == today:
        return "Today " + when.strftime("%H:%M")
    return when.strftime("%Y-%m-%d %H:%M")


def relative(path: str, root: str) -> str:
    """Path shown relative to the batch's folder when it's inside it."""
    if root and path and os.path.normcase(path).startswith(os.path.normcase(root) + os.sep):
        return os.path.relpath(path, root)
    return path


def describe(batch: dict) -> tuple[str, str]:
    """(action text, status text) for one journal batch."""
    n = len(batch["items"])
    if batch["kind"] == "recycle":
        action = f"Recycled {plural(n, 'file')}  ·  {batch.get('label', '')}"
        status = "In Recycle Bin" if n else "Nothing recycled"
    else:
        action = f"Moved {plural(n, 'file')}  ·  {batch.get('label', '')}"
        if batch.get("undone"):
            status = "Undone"
        elif not batch.get("finished"):
            status = "Interrupted · can undo"
        else:
            status = "Can undo" if n else "Nothing moved"
    if batch.get("skipped"):
        status += f"  ·  {len(batch['skipped'])} left alone"
    return action, status


class HistoryView(ToolView):
    title = "History & undo"
    subtitle = "Everything the app has done. Moves can be undone here."
    uses_folder = False

    def build(self) -> None:
        self.batches: list[dict] = []
        b = self.body
        b.grid_columnconfigure(0, weight=1)
        b.grid_rowconfigure(0, weight=3)
        b.grid_rowconfigure(2, weight=2)

        self.table = Table(b, [("when", "When", 120, "w"), ("action", "What happened", 270, "w", True),
                               ("size", "Size", 80, "e"), ("folder", "Folder", 220, "w", True),
                               ("status", "Status", 190, "w")], selectmode="browse")
        self.table.grid(row=0, column=0, sticky="nsew")
        self.table.tree.bind("<<TreeviewSelect>>", lambda _e: self._selected())

        head = ctk.CTkFrame(b, fg_color="transparent")
        head.grid(row=1, column=0, sticky="ew", pady=(14, 6))
        head.grid_columnconfigure(0, weight=1)
        self.detail_label = section_label(head, "Files in this batch")
        self.detail_label.grid(row=0, column=0, sticky="w")
        self.detail_hint = hint(head, "")
        self.detail_hint.grid(row=1, column=0, sticky="w")

        self.items = Table(b, [("src", "From (inside the folder above)", 420, "w"), ("dst", "To", 420, "w"),
                               ("size", "Size", 90, "e")], selectmode="browse")
        self.items.grid(row=2, column=0, sticky="nsew")
        self.items.tree.bind("<Double-1>", self._open_item)

        self.bin_btn = ghost_button(self.footer, "Open Recycle Bin", open_recycle_bin, width=150)
        self.undo_btn = primary_button(self.footer, "Undo", self._undo_selected, width=170)

    def on_show(self) -> None:
        self.reload()

    def show_undo_result(self, text: str, kind: str, acts: list) -> None:
        self.reload()
        self.status.show(text, kind, acts)

    def reload(self, select: str | None = None) -> None:
        current = select or (self.table.tree.selection() or [None])[0]
        self.batches = self.app.journal.newest_first()
        self.table.clear()
        for batch in self.batches:
            action, status = describe(batch)
            size = sum(i.get("size", 0) for i in batch["items"])
            undone = batch.get("undone")
            self.table.tree.insert("", "end", iid=batch["id"], values=(
                nice_time(batch["time"]), action, human_size(size),
                short_path(batch.get("root", ""), 44), status),
                tags=("undone",) if undone else (("muted",) if batch["kind"] == "recycle" else ()))
        self.table.show_empty("" if self.batches else
                              "Nothing yet. Moves and recycles you make will be listed here.")
        if current and self.table.tree.exists(current):
            self.table.tree.selection_set(current)
        elif self.batches:
            self.table.tree.selection_set(self.batches[0]["id"])
        self._selected()

    def _batch(self) -> dict | None:
        sel = self.table.tree.selection()
        return next((b for b in self.batches if b["id"] == sel[0]), None) if sel else None

    def _selected(self) -> None:
        batch = self._batch()
        self.items.clear()
        self.undo_btn.grid_remove()
        self.bin_btn.grid_remove()
        if not batch:
            self.items.show_empty("")
            self.detail_hint.configure(text="")
            return
        recycle = batch["kind"] == "recycle"
        root = batch.get("root", "")
        for i, item in enumerate(batch["items"]):
            self.items.tree.insert("", "end", iid=str(i), values=(
                relative(item["src"], root), "Recycle Bin" if recycle else relative(item.get("dst", ""), root),
                human_size(item.get("size", 0))))
        for j, (path, why) in enumerate(batch.get("skipped", [])):
            self.items.tree.insert("", "end", iid=f"s{j}", values=(relative(path, root),
                                   f"Left alone: {why}", ""), tags=("warn",))
        self.items.show_empty("" if batch["items"] or batch.get("skipped") else "No files in this batch.")
        if recycle:
            self.detail_hint.configure(text=RECYCLE_UNDO_HELP)
            self.bin_btn.grid(row=0, column=3, padx=(12, 0))
        elif batch.get("undone"):
            left = len(batch.get("undo_skipped", []))
            self.detail_hint.configure(text=f"Undone {nice_time(batch.get('undone_at', ''))}."
                                       + (f" {plural(left, 'file')} couldn't be put back." if left else ""))
        else:
            self.detail_hint.configure(text="Undo moves every file back to where it was.")
            if batch["items"]:
                self.undo_btn.grid(row=0, column=3, padx=(12, 0))
                self.undo_btn.set_enabled(True, f"Undo {plural(len(batch['items']), 'move')}")

    def _undo_selected(self) -> None:
        batch = self._batch()
        if batch:
            self.undo_batch(batch["id"])

    def _open_item(self, event) -> None:
        batch = self._batch()
        row = self.items.tree.identify_row(event.y)
        if not batch or not row or row.startswith("s"):
            return
        item = batch["items"][int(row)]
        for path in (item.get("dst"), item["src"]):
            if path and os.path.exists(path):
                open_in_explorer(path)
                return
