@echo off
chcp 65001 >nul
set "PYTHONDONTWRITEBYTECODE=1"
set "TEMP=D:\FEA Coursework\Workspace\_tmp"
set "TMP=D:\FEA Coursework\Workspace\_tmp"
"D:\anaconda3\python.exe" "D:\FEA Coursework\Workspace\scripts\control_gate.py" set RUN --reason "User clicked 01_CONTINUE_RUN.bat"
echo.
"D:\anaconda3\python.exe" "D:\FEA Coursework\Workspace\scripts\control_gate.py" status
echo.
echo [OK] Switch set to RUN. You can now tell GPT Astra: "Continue from checkpoint."
pause
