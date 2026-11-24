@echo off
rem Tutorial Studio: double-click to start, then use the browser tab that opens.
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Tutorial Studio is not installed yet. Double-click install.bat first.
  pause
  exit /b 1
)
echo Starting Tutorial Studio... keep this window open while you use it.
start "" cmd /c "timeout /t 4 /nobreak >nul & start http://127.0.0.1:8765"
".venv\Scripts\python.exe" -m studio
echo.
echo Tutorial Studio stopped.
pause
