"""Drives the real UI through every screen and saves screenshots (also a smoke test).

Usage: python scripts/screenshots.py [out_dir]
Needs demo/Downloads (run scripts/make_demo.py first). Recycling goes to demo/_bin, not the
real Recycle Bin, and the History journal is a throwaway file in demo/.
"""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
DEMO = ROOT / "demo"
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else DEMO / "shots"


def main() -> None:
    import ctypes
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
    from PIL import ImageGrab

    from app.core import actions
    from app.ui import widgets
    from app.ui.views import base, duplicates, organize, overview
    from app.ui.window import App

    # Fake bin and journal so a demo run never touches real user state.
    bin_dir = DEMO / "_bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    actions._default_trash = lambda p: os.rename(p, bin_dir / f"{len(os.listdir(bin_dir))}-{os.path.basename(p)}")
    yes = lambda *a, **k: True
    for mod in (base, duplicates, organize, overview, widgets):
        mod.confirm = yes

    OUT.mkdir(parents=True, exist_ok=True)
    app = App()
    app.journal = actions.Journal(DEMO / "journal.json")
    app.geometry("1280x840+30+30")
    steps = []
    log = []

    def shot(name):
        app.update()
        x, y = app.winfo_rootx(), app.winfo_rooty()
        img = ImageGrab.grab((x, y, x + app.winfo_width(), y + app.winfo_height()), all_screens=True)
        img.save(OUT / f"{name}.png")
        log.append(f"{name}: {app.current.status.label.cget('text')}")

    def wait_idle(then):
        def check():
            if app.worker.busy:
                app.after(100, check)
            else:
                app.after(400, then)
        app.after(300, check)

    def step(fn):
        steps.append(fn)
        return fn

    def run_next():
        if steps:
            steps.pop(0)()
        else:
            print("\n".join(log))
            app.destroy()

    @step
    def scan():
        app.set_folder(str(DEMO / "Downloads"))
        app.show("overview")
        app.views["overview"].start()
        wait_idle(run_next)

    @step
    def select_and_shoot():
        ov = app.views["overview"]
        ov.files.tree.selection_set(["1", "3"])
        app.update()
        shot("1-overview")
        run_next()

    @step
    def filters():
        ov = app.views["overview"]
        ov.months.insert(0, "12")
        ov.apply_filters()
        app.update()
        shot("2-overview-filtered")
        ov.clear_filters()
        ov.files.tree.selection_set(["0"])
        ov.recycle()
        wait_idle(run_next)

    @step
    def after_recycle():
        shot("3-overview-recycled")
        app.show("duplicates")
        app.views["duplicates"].start()
        wait_idle(run_next)

    @step
    def dupes_shot():
        shot("4-duplicates")
        app.views["duplicates"].recycle()
        wait_idle(run_next)

    @step
    def dupes_done():
        shot("5-duplicates-recycled")
        app.show("organize")
        wait_idle(run_next)

    @step
    def organize_shot():
        shot("6-organize-preview")
        app.views["organize"].apply()
        wait_idle(run_next)

    @step
    def organized():
        shot("7-organize-moved")
        app.show("history")
        app.update()
        shot("8-history")
        app.views["history"]._undo_selected()
        wait_idle(run_next)

    @step
    def undone():
        shot("9-history-undone")
        run_next()

    app.after(800, run_next)
    app.mainloop()


if __name__ == "__main__":
    main()
