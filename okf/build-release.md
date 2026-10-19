# Build & release

- `build.bat` creates `.venv`, installs `requirements.txt` and PyInstaller, **runs the tests**, then builds from `mjc-folder-cleaner.spec`.
- Output: one windowed exe, `dist\MJC Folder Cleaner.exe`, with `assets/`, the CustomTkinter themes and the tkdnd library bundled.
- CI: `.github/workflows/tests.yml` runs pytest on `windows-latest` with Python 3.12 on every push and PR. It includes one real Recycle Bin round trip (a 1-byte temp file).
- Releases: tag `vX.Y.Z`, then attach the exe to a GitHub Release. The README's download link points at `/releases/latest`.
- The exe is unsigned, so SmartScreen warns on first run ("More info → Run anyway"). Code signing costs money and is on the roadmap.
