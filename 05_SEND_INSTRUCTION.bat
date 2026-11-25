@echo off
chcp 65001 >nul
set "PYTHONDONTWRITEBYTECODE=1"
set "TEMP=D:\FEA Coursework\Workspace\_tmp"
set "TMP=D:\FEA Coursework\Workspace\_tmp"
echo ====================================================================
echo   Send Mid-Flight Instruction to GPT Astra / CFD Workflow
echo ====================================================================
echo Leave blank to open CONTROL\USER_INSTRUCTION.md in Notepad instead.
echo.
set /p user_msg="Enter instruction: "
if "%user_msg%"=="" (
    start "" notepad.exe "D:\FEA Coursework\Workspace\CONTROL\USER_INSTRUCTION.md"
    exit /b 0
)
"D:\anaconda3\python.exe" "D:\FEA Coursework\Workspace\scripts\control_gate.py" instruct "%user_msg%"
echo.
echo [OK] Instruction queued in CONTROL\USER_INSTRUCTION.md.
echo Note: If you also want to pause immediately, run 02_PAUSE_WORK.bat.
pause
