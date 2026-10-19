"""Errors the UI shows to people verbatim. Plain English, and say what to do next."""

from __future__ import annotations


class CleanerError(Exception):
    """Something the user can fix. The message is shown as-is."""


class Cancelled(Exception):
    """The user pressed Cancel."""

    def __init__(self, message: str = "Cancelled."):
        super().__init__(message)


def friendly_os_error(exc: OSError) -> str:
    """One short sentence explaining why a file couldn't be read or changed."""
    if isinstance(exc, PermissionError):
        return "Windows wouldn't allow access (it may be open in another app, or need admin rights)."
    if isinstance(exc, FileNotFoundError):
        return "It's gone (moved or deleted by something else)."
    if isinstance(exc, FileExistsError):
        return "Something with that name is already there."
    if getattr(exc, "winerror", None) == 32:
        return "Another app has it open. Close that app and try again."
    if getattr(exc, "winerror", None) == 206 or getattr(exc, "winerror", None) == 3:
        return "The path is too long or no longer exists."
    detail = exc.strerror or exc.__class__.__name__
    return f"Couldn't access it ({detail})."
