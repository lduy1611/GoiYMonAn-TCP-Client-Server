@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo Python virtual environment was not found at .venv\Scripts\python.exe
  pause
  exit /b 1
)

echo Starting the existing unified-v3 TEST_ONLY demo on fixed ports:
echo   Web:   8000
echo   TCP:   9000 (localhost only)
echo   MySQL: 63900 (localhost only)
echo Do not close this window while using the demo. Press Ctrl+C to stop it.
echo.

".venv\Scripts\python.exe" scripts\run_demo.py
if errorlevel 1 (
  echo.
  echo The demo did not start. Review the message above and statics\runtime\demo-fixed logs.
  pause
)

endlocal
