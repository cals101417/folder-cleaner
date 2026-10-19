"""Run slow folder work off the UI thread; deliver results back on it.

Tk isn't thread-safe, so the worker never touches widgets. It drops messages
in a queue that the UI polls every 50 ms. Jobs check `worker.cancel` to stop early.
"""

from __future__ import annotations

import queue
import threading
import time
import traceback
from typing import Any, Callable

from ..core.errors import Cancelled, CleanerError


class Worker:
    def __init__(self, root):
        self.root = root
        self.inbox: queue.Queue = queue.Queue()
        self.busy = False
        self.cancel = threading.Event()
        self._poll()

    def _poll(self) -> None:
        try:
            while True:
                callback, args = self.inbox.get_nowait()
                callback(*args)
        except queue.Empty:
            pass
        self.root.after(50, self._poll)

    def post(self, callback: Callable, *args: Any) -> None:
        """Call from the worker thread to run `callback(*args)` on the UI thread."""
        self.inbox.put((callback, args))

    def run(self, job: Callable[[], Any], on_done: Callable[[Any], None],
            on_error: Callable[[str], None],
            on_cancel: Callable[[str], None] | None = None) -> bool:
        if self.busy:
            return False
        self.busy = True
        self.cancel.clear()

        def target():
            try:
                result = job()
            except Cancelled as exc:
                self.post(self._finish, on_cancel or on_error, str(exc))
            except CleanerError as exc:
                self.post(self._finish, on_error, str(exc))
            except Exception as exc:  # unexpected: still shown to the user, so keep it readable
                traceback.print_exc()
                message = (f"Something went wrong ({exc.__class__.__name__}: {exc}). "
                           "Nothing else was changed. Try again, or pick another folder.")
                self.post(self._finish, on_error, message)
            else:
                self.post(self._finish, on_done, result)

        threading.Thread(target=target, daemon=True).start()
        return True

    def stop(self) -> None:
        self.cancel.set()

    def _finish(self, callback: Callable, value: Any) -> None:
        self.busy = False
        callback(value)


class Throttle:
    """Wraps a progress callback so the UI gets at most one update per `every` seconds."""

    def __init__(self, worker: Worker, callback: Callable, every: float = 0.1):
        self.worker, self.callback, self.every = worker, callback, every
        self.last = 0.0

    def __call__(self, *args) -> None:
        now = time.monotonic()
        if now - self.last >= self.every:
            self.last = now
            self.worker.post(self.callback, *args)
