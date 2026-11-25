# Launch (or resume) the unattended fast-track P2 -> P12 run as a fully detached process.
# Safe to run again: a second launch exits immediately (single-instance lock) and a relaunch after a
# crash/reboot resumes from the saved native checkpoints and the same compute deadline
# (use -RenewDeadline only to restart the compute clock for P2-P10).
param([switch]$RenewDeadline, [string]$FromStage = "P2", [double]$Hours = 15.0)
$ErrorActionPreference = "Stop"
$ws = "D:\FEA Coursework\Workspace"
. "$ws\scripts\env_d_only.ps1"
$py = "$ws\.venv\Scripts\python.exe"
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$launcher = "$ws\SUPERVISOR\_launch_orchestrator.cmd"
$extra = "--from-stage $FromStage --hours $Hours"
if ($RenewDeadline) { $extra += " --renew-deadline" }
# Double spawn through "cmd /c start": the orchestrator's parent exits at once, so closing or
# tree-killing the calling terminal/agent can never take the run down with it.
Start-Process -FilePath "cmd.exe" -ArgumentList "/c start `"X57 fast-track`" /min `"$launcher`" $stamp $extra" -WindowStyle Hidden
Start-Sleep -Seconds 25
Write-Host "Fast-track launch requested (console log: $ws\logs\fasttrack_console_$stamp.log)"
& $py -B "$ws\SUPERVISOR\fasttrack_monitor.py" --wait 0
