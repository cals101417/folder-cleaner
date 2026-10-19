# Build & release

- `build.bat` creates `.venv`, installs `requirements.txt` and PyInstaller, **runs the tests**, then builds from `mjc-folder-cleaner.spec`.
- Output: one windowed exe, `dist\MJC Folder Cleaner.exe`, with `assets/`, the CustomTkinter themes and the tkdnd library bundled.
- CI: `.github/workflows/tests.yml` runs pytest on `windows-latest` with Python 3.12 on every push and PR. It includes one real Recycle Bin round trip (a 1-byte temp file).
- Releases: `.github/workflows/release.yml`. Push a tag `vX.Y.Z` over SSH; the workflow tests, builds the exe on `windows-latest` and creates the GitHub Release with it attached, using the repo's own token. The local `gh` CLI is never used for this repo (it's signed in to a different account for work). The README's download link points at `/releases/latest`.
- The exe is unsigned, so SmartScreen warns on first run ("More info → Run anyway"). Code signing costs money and is on the roadmap.
