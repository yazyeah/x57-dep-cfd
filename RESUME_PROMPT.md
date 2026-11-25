# Resume Prompt for GPT Astra (暂停后继续工作提示词)

> After double-clicking `01_CONTINUE_RUN.bat` (which sets `CONTROL\STATE.txt` back to `RUN`), paste this short prompt to **GPT Astra** to resume cleanly from the exact saved checkpoint:

---

Please resume our X-57 DEP Aircraft Ansys CFD Coursework inside `F:\FEA Coursework\Workspace`.

1. Dot-source `F:\FEA Coursework\Workspace\scripts\env_f_only.ps1` (strictly zero C:/D: writes).
2. Run `control_gate.py check` and `control_gate.py status`, and inspect `CONTROL\CHECKPOINT.json`.
3. If there is a pending user instruction in `CONTROL\USER_INSTRUCTION.md` (exit code `40`), read, obey, and acknowledge it first.
4. Resume seamlessly from the latest incomplete/paused stage and saved Fluent checkpoint (`.cas.h5`/`.dat.h5`) without redoing already-verified completed stages, strictly following `AGENTS.md` and `skills\`.
5. Keep polling the Control Gate before/after every step and running Fluent exclusively via `scripts\run_fluent_managed.py`, until `scripts\verify_deliverables.py` passes with exit code `0`.
