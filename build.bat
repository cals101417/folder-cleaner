@echo off
REM Builds "dist\MJC Folder Cleaner.exe". Double-click this file, or run it from a terminal.
setlocal
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
  echo Python isn't installed. Get Python 3.12 from python.org and tick "Add python.exe to PATH".
  pause & exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo Creating virtual environment...
  python -m venv .venv || (pause & exit /b 1)
)

echo Installing dependencies...
".venv\Scripts\python.exe" -m pip install --upgrade pip -q
".venv\Scripts\python.exe" -m pip install -r requirements.txt pyinstaller -q || (pause & exit /b 1)

echo Running tests...
".venv\Scripts\python.exe" -m pip install pytest -q
".venv\Scripts\python.exe" -m pytest -q || (echo Tests failed, so no .exe was built. & pause & exit /b 1)

echo Building...
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean mjc-folder-cleaner.spec || (pause & exit /b 1)

echo.
echo Done: dist\MJC Folder Cleaner.exe
if not defined CI explorer dist
if not defined CI pause
