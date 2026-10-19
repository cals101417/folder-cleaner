# Decisions

- **Same stack and conventions as MJC PDF Kit** (CustomTkinter, Worker/post, theme tokens, config, okf). Reusing the patterns kept v0.1 fast, and the two apps feel like siblings.
- **ttk.Treeview for lists, not CTk widgets.** Each CTk row draws its own canvas, so 1,000 rows freeze the UI. Treeview handles 30k rows. Size bars are block characters in a column.
- **Overview shows direct subfolders, with drill-down.** Listing every nested folder would make `A`, `A\B` and `A\B\C` the three biggest.
- **The Recycle Bin pre-check exists** because send2trash calls the shell with FOF_NOCONFIRMATION. Windows then permanently deletes files that are too big for the bin or have no bin, without asking.
- **The quick hash runs on threads; the full hash doesn't.** Opening files dominates on Windows (antivirus hooks), and it releases the GIL: 73 s → 6.6 s on 100k files. Running big sequential reads in parallel would thrash spinning disks.
- **The journal is written when a batch starts and every 25 items**, so a crash mid-batch still leaves an undo trail. A damaged journal is renamed aside, never overwritten.
- **Undo marks the batch undone even if some files couldn't go back.** Those are stored in `undo_skipped` and shown in History.
- **Organize skips** partial downloads (`.crdownload`, `.part`…), `desktop.ini`, `~$` Office lock files, and hidden or system files.

- **Code projects are excluded (v0.1.1).** On a real Documents folder, v0.1.0 offered 15,533 "duplicate" groups, almost all inside `node_modules`. The bytes were identical, but recycling one breaks that project. Only strong markers count (`.git`, `package.json`, `pyproject.toml`, `.sln`…), not `requirements.txt` or `setup.py`, which turn up loose in Downloads. Drive roots, the user folder and its parent never count as projects, so a stray `package.json` in the user folder can't swallow everything. Overview still allows recycling inside a project (a 2 GB video in a repo can be real junk), but it warns first.
- **Duplicates default to files over 1 MB.** Tiny duplicates are noise; the real waste is media, installers and archives. With the project rule as well, that same Documents folder went from 15,533 groups to 0.
- **The demo folder lives in `Documents/MJC Cleaner Demo`**, outside the repo, because the repo itself is a code project.

## Out of scope for v0.1
Similar-image or fuzzy matching, cloud drives, scheduled cleaning, registry and temp-file "system cleaning", and macOS/Linux packaging. These are listed in the README roadmap.
