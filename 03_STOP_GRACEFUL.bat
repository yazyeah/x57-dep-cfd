@echo off
chcp 65001 >nul
set "PYTHONDONTWRITEBYTECODE=1"
set "TEMP=D:\FEA Coursework\Workspace\_tmp"
set "TMP=D:\FEA Coursework\Workspace\_tmp"
"D:\anaconda3\python.exe" "D:\FEA Coursework\Workspace\scripts\control_gate.py" set STOP --signal-fluent --reason "User clicked 03_STOP_GRACEFUL.bat"
echo.
"D:\anaconda3\python.exe" "D:\FEA Coursework\Workspace\scripts\control_gate.py" status
echo.
echo [OK] Switch set to STOP. Active jobs will checkpoint and stop cleanly.
pause
