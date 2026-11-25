@echo off
chcp 65001 >nul
set "PYTHONDONTWRITEBYTECODE=1"
set "TEMP=D:\FEA Coursework\Workspace\_tmp"
set "TMP=D:\FEA Coursework\Workspace\_tmp"
"D:\anaconda3\python.exe" "D:\FEA Coursework\Workspace\scripts\control_gate.py" status
echo.
pause
