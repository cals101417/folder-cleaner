# PyInstaller build recipe. Run via build.bat (Windows) or: pyinstaller --noconfirm mjc-folder-cleaner.spec
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files

ROOT = Path(SPECPATH)
# Only what the app loads at runtime (README screenshots stay out of the exe).
datas = [(str(ROOT / "assets" / n), "assets") for n in ("app.ico", "icon.png", "logo.png")
         if (ROOT / "assets" / n).exists()]
datas += collect_data_files("customtkinter")   # theme JSON files
datas += collect_data_files("tkinterdnd2")     # tkdnd native drag-and-drop library

a = Analysis(
    ["run.py"],
    pathex=[str(ROOT)],
    datas=datas,
    hiddenimports=["tkinterdnd2", "send2trash.win.legacy"],
    excludes=["pytest", "numpy"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    name="MJC Folder Cleaner",
    icon=str(ROOT / "assets" / "app.ico"),
    console=False,
    upx=False,
)
