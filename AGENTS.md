# AGENTS.md — X-57 DEP Aircraft Ansys CFD Coursework Workspace

## 0. FAST-TRACK MODE (overrides the rest of this file while active)
The remaining P2–P12 work runs unattended through `00_FASTTRACK_START.ps1` →
`SUPERVISOR\run_all_fasttrack.py`. Follow `GEMINI.md` and `FASTTRACK_RUNBOOK.md`: launch/monitor only,
never launch Fluent or the old P2 drivers by hand, never change thresholds in `scripts\fasttrack_profile.py`.
Definition of done in fast-track mode: orchestrator state `complete`, `verify_deliverables.py` exit 0
(integrity checks hard, physical targets reported as WARN), and `DELIVERABLES\final_quality_report.md` written.

This file governs ALL autonomous AI agents (including **GPT Astra**) operating in `D:\FEA Coursework\Workspace` (healthy internal NVMe SSD).

## 1. Hard Operational Rules
1. **Strict Workspace Isolation (`D:\FEA Coursework\Workspace`)**: NEVER write any project file, cache, temp file, log, or Python package to `C:`, old `E:`, or failing `F:`. Keep ALL writes strictly inside `D:\FEA Coursework\Workspace\`. NEVER modify read-only input files in `D:\FEA Coursework\` (`CW1-X-57.glb`, `CW1--X-57_metool.stl`, `CFD_Coursework.docx`). Always dot-source `D:\FEA Coursework\Workspace\scripts\env_d_only.ps1` first.
2. **Mandatory Control Gate ("开关口")**: Before and after every atomic step, run:
   ```powershell
   & "D:\FEA Coursework\Workspace\.venv\Scripts\python.exe" "D:\FEA Coursework\Workspace\scripts\control_gate.py" check
   ```
   - Exit `0`: Proceed.
   - Exit `40`: Read `CONTROL\USER_INSTRUCTION.md`, obey user's instruction, acknowledge with `control_gate.py ack-instruction --response "..."`, and re-check.
   - Exit `10` (`PAUSE`) or `20` (`STOP`) or `30` (`ABORT`): Save checkpoint to `CONTROL\CHECKPOINT.json`, ensure no orphan processes remain, summarize current state to the user, and **stop cleanly**.
3. **Managed Ansys Fluent Execution**: NEVER call `fluent.exe` directly. Always launch Fluent through `scripts\run_fluent_managed.py` so D:-workspace temp redirection, PID tracking, live logs, and graceful pause-and-checkpoint (`exit-fluent.txt`) work automatically.
4. **Zero Fabrication**: Never invent, tweak, or hardcode CFD results. Every reported number must trace directly to real converged Fluent/MAPDL outputs inside `D:\FEA Coursework\Workspace`.

## 2. Skills Directory (MUST READ BEFORE EACH PHASE)
Load and follow these modular skills in order:
1. `skills\e-drive-isolation-and-control-gate\SKILL.md` — Storage isolation, control switch & checkpoint/resume protocol.
2. `skills\x57-geometry-prep\SKILL.md` — Verified GLB/STL inch-to-meter scaling, unrotation, blade removal, actuator-disk placement & boundary naming.
3. `skills\ansys-fluent-dep-cfd\SKILL.md` — ANSYS Student v252 limits, Poly-Hexcore + `y+ ≈ 1` inflation, `k-omega SST`, Actuator-Disk with Swirl, full case matrix.
4. `skills\cfd-verification-and-physics-qa\SKILL.md` — Convergence criteria, ASME V&V 20 GCI, `y+` verification, RPM `s^2` scaling, swirl isolation & physical honesty.
5. `skills\aero-structural-fsi-stress\SKILL.md` — Fluid wall-shear/Reynolds stress + 1-Way FSI ANSYS MAPDL structural von Mises stress convergence & safety-factor verification.
6. `skills\top-venue-scientific-visualization\SKILL.md` — AIAA/JFM + CVPR/ICCV/NeurIPS fusion plotting aesthetics, `SciencePlots`/`tueplots`/`PyVista` recipes, inset zooms, ablation/Pareto/radar composites.
7. `skills\postproc-and-deliverables-packager\SKILL.md` — Final deliverables manifest & automated QA packaging.

## 3. Workspace Map
- `CONTROL\` — User switch (`STATE.txt`, `USER_INSTRUCTION.md`, `CHECKPOINT.json`, `STATUS.json`, `active_pids.json`)
- `01_CONTINUE_RUN.bat` .. `06_VIEW_STATUS.bat` — One-click user control switches
- `scripts\` — Pre-built environment, control gate, Fluent supervisor, geometry auditor & deliverables verifier
- `00_env_audit\` — Stage S0 Ansys Student v252 cell/core limit verification
- `01_geometry\` — Cleaned metric CAD/STL, blade-removed half-aircraft & disk specifications
- `02_mesh\` — Coarse, Medium, Fine Fluent Meshing projects & `.msh.h5`
- `03_cases\` — Fluent solver runs (`coarse_rpm100`, `medium_rpm100`, `fine_rpm100`, `medium_rpm050`, `medium_rpm075`, `medium_rpm100_noswirl`)
- `04_postproc\` — Real fluid cell slice exports, surface `Cp`, pathline exports & plotting scripts
- `DELIVERABLES\` — Final verified handoff bundle (`DELIVERABLES_MANIFEST.json`, `data\`, `figures\`, `fluent_renders\`, `ansys_submission\`, `handoff_notes.md`)
- `logs\`, `_tmp\`, `_cache\` — Redirected logs, temp & caches (strictly on `E:`)

## 4. Definition of Done
Work is complete ONLY when:
1. All stages `S0_ENV_AUDIT` through `S7_DELIVERABLES_PACK` are marked `done` in `CONTROL\CHECKPOINT.json`.
2. `scripts\verify_deliverables.py` exits with code `0` (`ALL CHECKS PASSED`).
3. Final Ansys submission files (`X57_DEP_fine_rpm100.msh.h5`, `.cas.h5`, `.dat.h5`) are verified reloadable in Fluent.

## 项目图表字体

所有绘图脚本统一使用 Times New Roman，覆盖标题、坐标与刻度、图例、色标、标注和数学符号（含粗体与斜体）。Matplotlib 使用 scripts/publication_fonts.py 中的 configure_matplotlib()；PNG 按 400 DPI 导出，矢量 PDF 嵌入实际 Times New Roman 字体。PyVista/VTK 出图前调用 configure_pyvista(plotter) 绑定相应 TTF。Fluent 原生视图调用 configure_fluent_font()，记录运行时实际支持及选用的字体，核验时如实列出任何不支持的原生文字元素。
