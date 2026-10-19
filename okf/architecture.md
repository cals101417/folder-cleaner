# Architecture

```
run.py → app.main → ui.window.App
                     ├─ sidebar (nav, "Recycle Bin only" badge, site link)
                     └─ stage → one ToolView at a time (created lazily on first visit)
ToolView (ui/views/base.py)
  header · FolderField · body · footer (StatusLine, Cancel, progress bar, actions)
  └─ calls app.core.* inside Worker.run(job, on_done, on_error, on_cancel)
```

## Layers
- `app/core/`: pure file logic, no tkinter. Functions take `guard`, `journal`, `progress` and `cancel` arguments, so tests can inject temp-folder rules and fakes.
  - `scan.scan()` → `ScanResult(files: list[FileRecord], folders, skipped, links_skipped, protected_skipped)`. A `FileRecord` holds the path, size, mtime_ns and Windows attributes.
  - `sizes.build_tree()` → cumulative bytes and file counts per folder. Overview shows the direct children of the current folder (double-click to drill down).
  - `dupes.find_duplicates()`: size groups → BLAKE2b of the first 64 KB (8 threads) → full BLAKE2b (one thread, so spinning disks don't thrash).
  - `organize.plan()` is a pure dry run; `organize.apply()` → `actions.move()`.
  - `actions`: `recycle`, `move`, `undo` and `Journal` (`%APPDATA%\MJC Folder Cleaner\journal.json`).
- `app/ui/`: CustomTkinter, plus ttk.Treeview (styled in `theme.style_tables`) for every list, because it stays fast with thousands of rows.
- `app/settings.py`: last folder, keep policy, organize mode.

## Shared state (on the App)
- `app.folder`: one folder shared by Overview, Duplicates and Organize. `set_folder` validates it with the guard.
- `app.scan`: the last ScanResult. Duplicates reuses it when it's for the same folder. Recycling updates it in place (`sizes.remove_files`); organize and undo clear it (`app.contents_changed()`).
- `app.journal`: one Journal instance for the whole app.

## Threading
`Worker` runs one job at a time on a daemon thread and owns a `cancel` Event that core functions poll. Results come back through a queue polled every 50 ms. `Throttle` limits progress posts to about 10 a second. Navigation and the folder picker are disabled while a job runs. Closing during a job asks first, cancels, then waits for the job to stop so the journal is flushed.

## Drag and drop
tkinterdnd2 is loaded on the root window. `App` mixes in `TkinterDnD.DnDWrapper` and registers itself, so a folder dropped anywhere on the window gets picked. If tkdnd fails to load, `widgets.DND_READY` stays false and the picker says "Choose a folder".
