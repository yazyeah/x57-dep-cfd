# One-shot: load the 2026-11-24 quality update into the running fast-track job.
# Returns immediately; a detached helper waits for the next safe point between Fluent steps,
# restarts the orchestrator once and logs to logs\fasttrack_update.log. Idempotent.
$ErrorActionPreference = "Stop"
$ws = "D:\FEA Coursework\Workspace"
. "$ws\scripts\env_d_only.ps1"
$py = "$ws\.venv\Scripts\python.exe"
if (Test-Path "$ws\SUPERVISOR\fasttrack_update_applied.json") {
    Write-Host "Update already applied:"; Get-Content "$ws\SUPERVISOR\fasttrack_update_applied.json"; exit 0
}
Start-Process -FilePath "cmd.exe" -ArgumentList "/c start `"X57 update`" /min `"$py`" -B `"$ws\SUPERVISOR\fasttrack_apply_update.py`"" -WindowStyle Hidden
Start-Sleep -Seconds 15
Write-Host "Update helper started. Progress:"
if (Test-Path "$ws\logs\fasttrack_update.log") { Get-Content "$ws\logs\fasttrack_update.log" -Tail 5 }
