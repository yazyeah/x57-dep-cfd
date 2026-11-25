# Bounded status poll: waits at most -Wait seconds, prints one JSON summary, returns
# 0 RUNNING | 1 HALTED | 2 COMPLETE | 3 ORCHESTRATOR_NOT_RUNNING (re-run 00_FASTTRACK_START.ps1).
param([int]$Wait = 900)
$ws = "D:\FEA Coursework\Workspace"
& "$ws\.venv\Scripts\python.exe" -B "$ws\SUPERVISOR\fasttrack_monitor.py" --wait $Wait
exit $LASTEXITCODE
