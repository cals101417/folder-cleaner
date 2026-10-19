# Log

- **2026-10-19**: v0.1.0 built. Core (scan, sizes, dupes, rules, actions, organize) with tests. UI with Overview, Duplicates, Organize and History & undo. Added a Recycle Bin pre-check that blocks silent permanent deletes. Benchmarked 100k files: scan 0.4 s, duplicates 6.6 s in the worst case, cancel under 0.2 s. Full UI flow verified with `scripts/screenshots.py`.
