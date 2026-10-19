@echo off
REM Runs the app from source (for development). Use build.bat to make the .exe.
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  python -m venv .venv
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt -q
)
".venv\Scripts\pythonw.exe" run.py
