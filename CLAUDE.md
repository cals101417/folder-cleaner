# CLAUDE.md

Offline Windows app (Python + CustomTkinter) that shows what's taking up space, finds duplicate files and tidies messy folders. Branded for mcalignerdev.com; sibling of MJC PDF Kit.

## Before you change anything
- Read `okf/index.md` and follow links only to the concepts your change touches. Append to `okf/log.md` after meaningful changes; never rewrite it.
- Keep `app/core/` free of UI imports. UI goes in `app/ui/`.
- Long work runs through `ui.worker.Worker`; never touch widgets from a worker thread (use `worker.post` or `Throttle`).
- Error messages are shown to end users verbatim: plain English, say what to do next. Raise `core.errors.CleanerError` for those.

## Safety rules (tested; never weaken them)
- No permanent deletes. Deletes go only through `core.actions.recycle` (send2trash plus `recycle_bin_problem`). No `os.remove`, `unlink`, `rmtree`, `shutil.move` or `os.replace` in `app/core/`; `tests/test_organize_rules.py` greps for them.
- Moves use `os.rename` (same drive, never overwrites) through `core.actions.move`, which journals them for undo.
- Scanning never follows symlinks or junctions. Protected paths come from `core.rules.Guard`; not user-overridable.
- Re-check size and mtime (`stale_reason`) before every recycle or move. Confirm dialog before every batch.

## Commands
- Run from source: `run.bat` (or `python run.py`)
- Tests: `python -m pytest -q`
- UI smoke run and screenshots: `python scripts/make_demo.py`, then `python scripts/screenshots.py`
- Build exe: `build.bat` → `dist\MJC Folder Cleaner.exe`

## Brand
Colors and fonts live only in `app/ui/theme.py`. Name and links only in `app/config.py`.
