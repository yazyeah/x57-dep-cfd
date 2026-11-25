@echo off
chcp 65001 >nul
set "PYTHONDONTWRITEBYTECODE=1"
set "TEMP=D:\FEA Coursework\Workspace\_tmp"
set "TMP=D:\FEA Coursework\Workspace\_tmp"
"D:\anaconda3\python.exe" "D:\FEA Coursework\Workspace\scripts\control_gate.py" set PAUSE --signal-fluent --reason "User clicked 02_PAUSE_WORK.bat"
echo.
"D:\anaconda3\python.exe" "D:\FEA Coursework\Workspace\scripts\control_gate.py" status
echo.
echo [OK] Switch set to PAUSE. Active Fluent/Python jobs will save checkpoint and pause cleanly.
pause
