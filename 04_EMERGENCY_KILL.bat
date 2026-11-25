@echo off
chcp 65001 >nul
set "PYTHONDONTWRITEBYTECODE=1"
set "TEMP=F:\FEA Coursework\Workspace\_tmp"
set "TMP=F:\FEA Coursework\Workspace\_tmp"
echo [WARNING] This will set state to ABORT and force-kill tracked Fluent/Python worker PIDs.
set /p confirm="Type YES to confirm emergency kill: "
if /I not "%confirm%"=="YES" (
    echo Cancelled.
    pause
    exit /b 0
)
"D:\anaconda3\python.exe" "F:\FEA Coursework\Workspace\scripts\control_gate.py" set ABORT --reason "User clicked 04_EMERGENCY_KILL.bat"
"D:\anaconda3\python.exe" "F:\FEA Coursework\Workspace\scripts\control_gate.py" kill-tracked
echo.
"D:\anaconda3\python.exe" "F:\FEA Coursework\Workspace\scripts\control_gate.py" status
pause
