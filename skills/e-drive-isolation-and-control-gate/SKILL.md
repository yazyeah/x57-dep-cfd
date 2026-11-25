---
name: e-drive-isolation-and-control-gate
description: Enforces strict D:\FEA Coursework\Workspace write isolation (zero C:/E:/F: writes) and mandatory user interrupt/pause/resume/instruction control gate protocol for every command and Ansys Fluent run.
---

# D-Workspace Isolation & User Control Gate ("开关口")

## 1. Non-Negotiable Storage Rule (ZERO C:, E:, or Failing F: Writes)

1. **All created, modified, temporary, cached, and output files MUST stay inside `D:\FEA Coursework\Workspace\`.**
2. **NEVER write to `C:`, old `E:`, or failing `F:`**, and **NEVER modify** the original read-only input files in `D:\FEA Coursework\` (`CW1-X-57.glb`, `CW1--X-57_metool.stl`, `CFD_Coursework.docx`).
3. **Before running ANY shell command, Python script, or Ansys Fluent job**, source the isolation script:
   ```powershell
   . "D:\FEA Coursework\Workspace\scripts\env_d_only.ps1"
   ```
   This redirects `TEMP`, `TMP`, `TMPDIR`, `FLUENT_TMPDIR`, `AWP_TEMP_DIR`, `ANSYS_TEMP_DIR`, `ANSYS_SCRATCH_DIR`, `MPLCONFIGDIR`, `PIP_CACHE_DIR`, `UV_CACHE_DIR`, `XDG_CACHE_HOME` strictly to `D:\FEA Coursework\Workspace\_tmp` and `_cache`, disables `.pyc` creation (`PYTHONDONTWRITEBYTECODE=1`), and forces English Fluent logs (`AWP_LOCALE252=en-us`).
4. **Python environment rule**:
   - Use the prebuilt workspace-local venv `D:\FEA Coursework\Workspace\.venv\Scripts\python.exe` (automatically exposed as `$env:X57_PYTHON` by `env_d_only.ps1`).
   - **NEVER run `pip install` or `conda install` into `C:` or global `D:\anaconda3`.** Only install into `D:\FEA Coursework\Workspace\.venv` with `UV_CACHE_DIR` / `PIP_CACHE_DIR` redirected to `D:\FEA Coursework\Workspace\_cache`.
5. **Disk hygiene on D: (~131 GB free NVMe SSD)**:
   - Keep `D:` free space above `10 GB` at all times.
   - Use Fluent HDF5 compressed formats (`.msh.h5`, `.cas.h5`, `.dat.h5`), keep only the latest 2 auto-save snapshots per active case, and periodically clean obsolete `_tmp\` scratch files after a stage completes.

---

## 2. Mandatory Control Gate ("开关口") Protocol

The user may pause, stop, abort, or send a new mid-flight instruction at **ANY** moment via the one-click `.bat` switches in `F:\FEA Coursework\Workspace\` or by editing `CONTROL\STATE.txt` and `CONTROL\USER_INSTRUCTION.md`.

### Check Before AND After Every Atomic Step
Run:
```powershell
& $env:X57_PYTHON "F:\FEA Coursework\Workspace\scripts\control_gate.py" check
```
Handle the exit code strictly:
- **Exit `0` (`RUN`, no pending instruction)**: Safe to proceed to the next step.
- **Exit `40` (`INSTRUCTION_PENDING`)**:
  1. Read `pending_instruction` from the JSON output (or `CONTROL\USER_INSTRUCTION.md`).
  2. Immediately adapt your plan/parameters to obey the user's instruction.
  3. Acknowledge it so it is archived in `CONTROL\INSTRUCTION_HISTORY.log`:
     ```powershell
     & $env:X57_PYTHON "F:\FEA Coursework\Workspace\scripts\control_gate.py" ack-instruction --response "<concise summary of how you applied it>"
     ```
  4. Re-run `control_gate.py check` before continuing.
- **Exit `10` (`PAUSE`)**:
  1. Do **NOT** launch any new solver or heavy step.
  2. Ensure current progress and resume pointers are saved to `CONTROL\CHECKPOINT.json`:
     ```powershell
     & $env:X57_PYTHON "F:\FEA Coursework\Workspace\scripts\control_gate.py" checkpoint-update --stage <STAGE_ID> --status paused --case <CASE> --fluent-ckpt <PATH_OR_EMPTY> --note "Paused cleanly at user request"
     ```
  3. Report a concise checkpoint status summary to the user (what finished, exact saved checkpoint file, what will run next when resumed) and **STOP your turn cleanly** so the user regains full control of their machine.
- **Exit `20` (`STOP`)**:
  1. Save final checkpoint (`--status paused` for unfinished stage), clean up any active tracked PIDs, summarize exact state, and **STOP cleanly**.
- **Exit `30` (`ABORT`)**:
  1. Run `control_gate.py kill-tracked` if any process remains, record aborted status in `CONTROL\CHECKPOINT.json`, and **STOP immediately**.

### Mandatory Managed Fluent Launcher
**NEVER invoke `fluent.exe` directly.** Always launch Fluent through:
```powershell
& $env:X57_PYTHON "F:\FEA Coursework\Workspace\scripts\run_fluent_managed.py" `
    --mode <meshing|solver> `
    --dim 3ddp `
    --procs <N> `
    --workdir "<F:\FEA Coursework\Workspace\...>" `
    --journal "<path\to\journal.jou>" `
    --stage <STAGE_ID> `
    --case <CASE_NAME>
```
What `run_fluent_managed.py` automatically guarantees:
1. Enforces all F:-drive `TEMP`/`TMP`/`FLUENT_TMPDIR` and `AWP_LOCALE252=en-us` variables.
2. Registers the Fluent PID in `CONTROL\active_pids.json` and unregisters on exit.
3. Streams live transcript logs into `F:\FEA Coursework\Workspace\logs\` and updates `CONTROL\STATUS.json` heartbeats.
4. Runs a 2-second watchdog thread: if the user triggers `PAUSE` or `STOP` (or queues an urgent instruction while running), it automatically drops Fluent's native `exit-fluent` trigger file into `--workdir`, allowing Fluent to finish the current iteration, write a clean `.cas.h5`/`.dat.h5` checkpoint, and exit without data corruption.
5. Returns structured exit codes (`0` = completed, `10` = paused gracefully by user, `20` = stopped gracefully by user, `30` = aborted, nonzero = solver error).

### Checkpoint Ledger Discipline
Always start a session by inspecting `CONTROL\CHECKPOINT.json` via:
```powershell
& $env:X57_PYTHON "F:\FEA Coursework\Workspace\scripts\control_gate.py" status
```
- **Resume rule**: Skip stages already marked `"done"` whose verified output artifacts exist on disk. Resume `"paused"` or `"in_progress"` stages from `last_fluent_checkpoint` (loading the saved `.cas.h5`/`.dat.h5` instead of restarting from iteration 0!).
- Update `CONTROL\CHECKPOINT.json` at every stage start (`in_progress`), pause (`paused`), and completion (`done`).
