"""Entry point: python -m app.main  (or run.py / the built .exe)."""

import sys


def main() -> None:
    if sys.platform == "win32":
        try:  # crisp text on high-DPI screens
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            pass
    from app.ui.window import App
    App().mainloop()


if __name__ == "__main__":
    main()
