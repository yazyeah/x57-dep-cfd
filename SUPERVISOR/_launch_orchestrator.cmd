@echo off
rem Detached launcher for the fast-track orchestrator. Usage: _launch_orchestrator.cmd STAMP [orchestrator args]
rem Started through "cmd /c start", so the orchestrator is not part of the calling terminal's process tree.
setlocal
set "WS=D:\FEA Coursework\Workspace"
cd /d "%WS%"
set "STAMP=%~1"
shift
"%WS%\.venv\Scripts\python.exe" -B "%WS%\SUPERVISOR\run_all_fasttrack.py" %1 %2 %3 %4 %5 %6 %7 %8 %9 > "%WS%\logs\fasttrack_console_%STAMP%.log" 2> "%WS%\logs\fasttrack_console_%STAMP%.err.log"
