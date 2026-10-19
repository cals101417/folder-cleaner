"""Shared layout for every screen: header, folder picker, body, footer (status + actions)."""

from __future__ import annotations

import customtkinter as ctk

from .. import theme as t
from ..widgets import (FolderField, StatusLine, confirm, ghost_button, open_recycle_bin, plural,
                       show_list)
from ...core import actions
from ...core.actions import RECYCLE_UNDO_HELP
from ...core.errors import CleanerError
from ...core.sizes import human_size


class ToolView(ctk.CTkFrame):
    title = ""
    subtitle = ""
    uses_folder = True

    def __init__(self, master, app):
        super().__init__(master, fg_color=t.BG, corner_radius=0)
        self.app = app
        self.settings = app.settings
        self.worker = app.worker
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        head = ctk.CTkFrame(self, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew", padx=32, pady=(26, 14))
        ctk.CTkLabel(head, text=self.title, font=t.font(24, "bold"), text_color=t.TEXT,
                     anchor="w").pack(anchor="w")
        ctk.CTkLabel(head, text=self.subtitle, font=t.font(13), text_color=t.MUTED,
                     anchor="w").pack(anchor="w", pady=(2, 0))

        self.folder_field = None
        if self.uses_folder:
            self.folder_field = FolderField(self, app, app.set_folder)
            self.folder_field.grid(row=1, column=0, sticky="ew", padx=32, pady=(0, 14))

        self.body = ctk.CTkFrame(self, fg_color="transparent")
        self.body.grid(row=2, column=0, sticky="nsew", padx=32)

        foot = ctk.CTkFrame(self, fg_color="transparent")
        foot.grid(row=3, column=0, sticky="ew", padx=32, pady=(12, 20))
        foot.grid_columnconfigure(0, weight=1)
        self.status = StatusLine(foot)
        self.status.grid(row=0, column=0, sticky="ew")
        self.cancel_btn = ghost_button(foot, "Cancel", self.cancel, width=90)
        self.progress = ctk.CTkProgressBar(foot, height=4, corner_radius=2, fg_color=t.SURFACE_2,
                                           progress_color=t.GOLD, mode="indeterminate")
        self.footer = foot

        self.build()

    def build(self) -> None:  # overridden by each screen
        raise NotImplementedError

    # ----- hooks from the window -----
    def on_folder_changed(self, folder: str) -> None:
        if self.folder_field:
            self.folder_field.set_folder(folder)

    def on_show(self) -> None:
        pass

    # ----- busy state -----
    def set_busy(self, busy: bool, text: str = "", cancellable: bool = True) -> None:
        if busy:
            self.progress.configure(mode="indeterminate")
            self.progress.grid(row=1, column=0, columnspan=4, sticky="ew", pady=(10, 0))
            self.progress.start()
            self.status.show(text or "Working…", "busy")
            if cancellable:
                self.cancel_btn.configure(state="normal", text="Cancel")
                self.cancel_btn.grid(row=0, column=1, padx=(16, 0))
        else:
            self.progress.stop()
            self.progress.grid_remove()
            self.cancel_btn.grid_remove()
        if self.folder_field:
            self.folder_field.set_enabled(not busy)
        self.app.set_nav_enabled(not busy)

    def set_progress(self, fraction: float | None) -> None:
        """Switch to a real percentage once the total is known."""
        if fraction is None:
            return
        if self.progress.cget("mode") != "determinate":
            self.progress.stop()
            self.progress.configure(mode="determinate")
        self.progress.set(max(0.0, min(1.0, fraction)))

    def cancel(self) -> None:
        self.worker.stop()
        self.cancel_btn.configure(state="disabled", text="Stopping…")

    def failed(self, message: str) -> None:
        self.set_busy(False)
        self.status.show(message, "error")

    def cancelled(self, message: str) -> None:
        self.set_busy(False)
        self.status.show(f"{message} Nothing was changed.", "warn")

    # ----- action results -----
    def describe_report(self, report, verb: str, where: str = "") -> tuple[str, str]:
        """Status text and kind for a recycle/move report, e.g. "Sent 3 files (2 MB) to the Recycle Bin."."""
        n, skipped = len(report.done), len(report.skipped)
        text = f"{verb} {plural(n, 'file')} ({human_size(report.bytes_done)}){where}."
        if report.cancelled:
            text = f"Stopped part-way. {text}"
        if skipped:
            text += f" {plural(skipped, 'file')} left alone."
        kind = "ok" if n and not skipped else ("warn" if skipped or report.cancelled else "info")
        return text, kind

    # ----- undo (Organize's shortcut and the History screen share this) -----
    def undo_batch(self, batch_id: str) -> None:
        if self.worker.busy:
            return
        try:
            batch = self.app.journal.get(batch_id)
        except CleanerError as exc:
            self.status.show(str(exc), "error")
            return
        if batch["kind"] == "recycle":
            self.status.show(RECYCLE_UNDO_HELP, "info", [("Open Recycle Bin", open_recycle_bin)])
            return
        n = len(batch["items"])
        if not confirm(self, "Undo this?", f"{plural(n, 'file')} will move back to where "
                       f"{'it was' if n == 1 else 'they were'}.", "Undo", danger=False,
                       detail="Files that were changed or replaced since then are left where they are."):
            return
        self.set_busy(True, "Putting files back…", cancellable=False)
        self.worker.run(lambda: actions.undo(batch_id, journal=self.app.journal, guard=self.app.guard),
                        self._undone, self.failed)

    def _undone(self, report) -> None:
        self.set_busy(False)
        self.app.contents_changed()
        text, kind = self.describe_report(report, "Put back")
        self.show_undo_result(text, kind, [a for a in [self.skipped_action(report)] if a])

    def show_undo_result(self, text: str, kind: str, acts: list) -> None:
        self.status.show(text, kind, acts)

    def on_contents_changed(self) -> None:
        """Files were moved or recycled; drop anything cached from the old scan."""

    def skipped_action(self, report, title: str = "Files left alone"):
        if not report.skipped:
            return None
        return ("See why", lambda: show_list(
            self, title, "These files weren't touched. Nothing happened to them.", report.skipped))
