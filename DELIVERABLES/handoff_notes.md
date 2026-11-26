# X-57 static taxi CFD handoff

**Work in progress.** P0 and P1 have passed their checks. The time-stamped stage ledger in `CONTROL/CHECKPOINT.json` governs resume. Aircraft force, pressure and convergence results require accepted Fluent solves. Files beneath `00_env_audit` are startup and software-validation fixtures and must never be used as aircraft results.

## Geometry and reference quantities

The coordinates are metres in the level CAD frame. Positive x points aft, positive y points up and positive z points starboard. The supplied STL carries the scene quaternion from the GLB. Applying its inverse and converting inches to metres gave a spanwise bounds mismatch of 0.006 mm. The starboard CAD has six five-bladed high-lift propellers and one three-bladed wingtip propeller. Connected-shell extraction removed the 33 frozen blades. Retained surface labels distinguish the wing, fuselage, nacelles, sponson and empennage. The simulation domain uses the starboard half of the aircraft. The eventual force reports must retain the raw half-domain values and double the x- and y-components for full-aircraft totals.

The cleaned surfaces are supplied in `01_geometry/cad_patches`. The external fluid boundary for remeshing uses a 6 mm lattice to join overlapping CAD components. The final STL reload yielded one closed boundary, 84,950 triangles and consistent edge winding. Five wing-section checks at x = 0 m were within 0.35 mm of the original CAD skins. The 6 mm construction can round sharper features. The measured open sponson-to-nacelle clearance at x = 0, z = 0.860 m was 0.77853158 m in the CAD and 0.7802708 m in the mesher input. The HLP-1 axis at z = 0.88832 m does not intersect the sponson at x = 0. Use separate annotations for these locations. Each Fluent volume mesh requires its own gap check. The domain extends from x = −18 to 30 m, y = −1.70 to 18 m, and z = 0 to 20 m.

Integrating wing chords over 513 stations, including the centerbox, gives a full planform area of 6.19335531 m², a mean aerodynamic chord of 0.64921853 m, and a span of 9.63834190 m. The reference quantities in the geometry audit supersede its earlier approximate exposed-chord estimate. The static reference convention uses the nominal annular actuator area and prescribed thrust to set a single positive reference dynamic pressure for all cases. The final coefficient table must record its exact value and retain dimensional gauge pressure and force.

## Actuator inputs

Each source region is a 0.050 m axial slab. Its inner radius clears the largest measured spinner section in that slab. All 33 CAD blade sections examined for handedness give starboard inboard-up rotation. The reflected port side uses the opposite axial torque. This is specific to this coursework CAD. The simulator configuration documented by NASA has different adjacent high-lift rotor handedness. See the source links and blade-section measurements in `data/actuator_disk_model.json`.

HLP thrust and torque use a near-static extrapolation of the NASA deployed-propeller performance map and a change to the modeled diameter and speed. The wingtip model uses CAD section measurements, a surrogate section polar and a collective setting adjusted to the 127.5 N·m torque reference at 2700 RPM. Its collective and thrust are model assumptions. In the matched swirl-off case the axial target remains the same and imposed tangential momentum goes to zero. The nominal source targets and RPM² schedules are prescribed model inputs. Report integrated force and torque for every source on every actual grid before quoting them as verified loads.

## Reproducibility

The managed solver reported a 1,048,576-cell threshold and its licensing diagnostic denied a five-rank checkout after four ranks were available. Production runs use at most four MPI ranks. Source the workspace F-drive environment and use the managed launcher for every Fluent job. It shares the Student seat between jobs, redirects the Fluent profile, and watches the user's control switch. Each production journal must save checkpoints and check the switch before subsequent work. Refer to `data/environment_and_license.json` for the audit evidence and its limits.


## Autonomous Decisions & Deviations Log

### 2026-11-23, 02:45 Pacific — three-dimensional solver configuration

- The matched 10 m/s ground-roll sensitivity uses nominal calibrated actuator thrust and torque, +x freestream, and +x runway speed in the aircraft-fixed frame. This isolates freestream and runway motion at prescribed loading. The NASA high-lift map varies with advance ratio and collective, so this case alone does not establish an installed propeller performance curve. The out-of-ground-effect sensitivity replaces the runway with a zero-gauge ambient pressure opening at the original lower boundary. Domain placement limits its interpretation as an unbounded free-air case.
- The high-lift-only and wingtip-only cases switch off both axial and tangential source terms on the omitted disks. The alternating-rotation case reverses HLPs 2, 4 and 6. The -10-degree high-lift vector case rotates the source support and its thrust/torque basis together about each original disk center. Its calibration stays fixed in that basis. The realizable k-epsilon sensitivity uses enhanced wall treatment and an epsilon residual. The SST cases request curvature correction, production limiting, and warped-face gradient correction. In every case confirm the runtime settings in its physics record.
- Forces act on the aircraft walls. Drag and lift are positive aft (+x) and up (+y). Positive pitching moment is about +z through the CAD origin (0, 0, 0) m. Both mirrored sides contribute to the full-aircraft Mz, so double the half-model moment and retain units of N m. Its near-zero drift and standard-deviation redlines are 0.5 N m and 1.0 N m. This is a moment about the declared origin, with no measured center of gravity supplied. Native force reports also retain pressure and viscous contributions by component.
- A matched-grid warm start (or medium-to-fine interpolation) can start and remain below a residual threshold. Report this separately from achieving a four-decade reduction. Check each residual over its full child-case history before attributing this exception to the initial condition. The acceptance audit also reports preferred 0.3% force/moment dispersion, the final 50-step continuity maximum and the change between two 25-step windows.
- Extract volume fields from the saved Fluent state at cell centers. Record the field aliases selected at runtime and preserve native global cell ID, coordinates and static pressure for checking the mapping to CFF data. For fine-grid closure analysis retain both off-diagonal velocity gradients and turbulent dynamic viscosity. In an eddy-viscosity closure the modeled shear stress is -rho<u'v'> = mu_t(du/dy+dv/dx). It is a modeled quantity. Consult the [Fluent field definitions](https://ansyshelp.ansys.com/public/Views/Secured/corp/v252/en/flu_ug/flu_ug_fvdefs.html) and the [ASCII export instructions](https://ansyshelp.ansys.com/public/Views/Secured/corp/v252/en/flu_ug/flu_ug_sec_file_export_steps.html).
- Before resumption, the native 12-cell synthetic fixture validated momentum projection and wrote a case/data pair. During P2 the actuator algebra was exercised offline on synthetic samples for 14 three-dimensional configurations including the zero-power equilibrium. Those samples serve only as configuration checks. Validate all seven disks and each numerical option in each production solve.

### 2026-11-23, 02:54 Pacific — restart, mesh input checks and typography

- The first GUI launch after resumption returned before its GUI process tree had finished. The managed launcher now requests the Fluent launcher wait option, starts the child suspended, attaches it to the Windows job and resumes it. It retains the seat until the job ends. A disposable Windows process-tree check verified that closing the job handle terminated the child. The Codex interface button itself was not exercised during this check. Runtime is documented by [Ansys](https://ansyshelp.ansys.com/public/Views/Secured/corp/v242/en/flu_ug/flu_ug_BatchExecution.html) and [Microsoft](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects).
- After resumption the latest native HDF5 at the mesh stage contained only surface entities. There was no production solution to restore. The recovery scanner checks the native case reference and cell data in each solution file and distinguishes surface-only and volume meshes. The GUI transcript is now watched for journal errors because a failed journal can leave the GUI open after the launcher returns.
- At x=0 m the five wing thickness stations are z=1.2, 1.8, 2.3, 3.5 and 4.3 m. Maximum absolute input-to-CAD thickness differences for iso45, iso35, iso30 and the 18 mm wing/40 mm other-body surface were 0.596, 0.596, 0.683 and 0.573 mm. Their sponson clearance errors at z=0.860 m were +4.159, +2.786, +2.662 and +3.694 mm. Recheck all accepted native volume meshes. The 3 mm target and 8 mm redline apply to the actual open clearance.
- Scripted figure text and mathematical labels use Times New Roman. The figure validator checks the embedded font programs in each vector PDF and reads actual PNG pixel density. Figure 1 has 2880 by 2039 pixels, 399.9992 DPI and two embedded Times New Roman faces. The PDF retains vector geometry. See 01_geometry/fig01_typography_qa.json for file hashes.

### 2026-11-23, 02:59 Pacific — native mesh quality verification

The current half-model count windows are 310,000–350,000, 620,000–660,000 and 1,020,000–1,044,000. The separate Fine ceiling is 1,045,000, below the 1,048,576-cell Student threshold. Adjacent effective spacing ratios must exceed 1.10. The grid audit records the actual minimum volume, minimum orthogonal quality, maximum aspect ratio, connectivity, CAD clearance and five disjoint refinement-region counts. For the volume allocation, wing-anchored prism columns take precedence over the seven 0.050 m loading annuli, followed by the near-wake box, other aircraft prisms or the mid-wake box, and the remaining exterior. The box limits come from each attempt's BOI mesh. Cell counts use volume centroids and the actual mesh topology. The mesh also supplies per-column layer counts, a volume-over-base-area height, ambient cell size distributions, and four axial plus four radial sample lines per disk. A ray that intersects a solid boundary is flagged. Requested mesh settings are listed separately.

Reopen the written Fluent mesh in solution mode using the journal generated by `verify_mesh_level.py --prepare-solver-check`. That journal records the mesh SHA-256 and prints the default and enhanced quality reports in separate sections. The standard orthogonal quality of a hex or poly cell derives from normalized face-area-vector projections onto cell-to-face and cell-to-neighbor centroid vectors. A tetrahedral, prism or pyramid cell also uses one minus its skewness as an upper bound. The enhanced metric additionally measures face distortion and local concavity. Use the standard metric for a like-for-like minimum, retaining the enhanced value as a thin-prism diagnostic. Each field solve supplies the wall y-plus values used to assess wall resolution. [Fluent 2025 R2 mesh quality definitions](https://ansyshelp.ansys.com/public/Views/Secured/corp/v252/en/flu_ug/flu_ug_GridQuality.html)

For the vectored case record the pressure and viscous wall forces, the discrete propulsor reaction (negative volume integral of the momentum source), and their sum. Keeping the direct vertical propulsor force identifiable is necessary when interpreting the aerodynamic lift increment.

- For P5, report the unequal refinement ratios, apparent order, both pairwise approximate errors, fine extrapolated relative error, fine and medium GCIs, and the asymptotic ratio. The coursework defines a spacing-ratio threshold of 1.1. Celik et al. describe a ratio greater than 1.3 as desirable. Report both criteria with their actual values. [Celik et al., Journal of Fluids Engineering](https://doi.org/10.1115/1.2960953).

### 2026-11-23, 03:12 Pacific — matched-case postprocessing

The figure 13 interaction is a four-case contrast, full loading minus high-lift-only minus wingtip-only plus the unpowered static equilibrium. The ground-roll and lower-boundary substitutions use the same prescribed nominal rotor loading. For model sensitivity, compare the pressure on the actual wing faces at HLP-3, the axial wake velocity at x = 0.35 m, and the integrated spanwise load on matched grids. The two-dimensional design comparisons share the original CAD chord, a depth of 1 m and the same nominal dynamic pressure as the three-dimensional aircraft cases (305.936114757 Pa). Report the length-weighted inlet-adjacent speed independently. The five-design frontier maximizes lift while minimizing drag. The 18-case heatmap scales its columns separately in the three-dimensional and two-dimensional groups and retains raw dimensional and coefficient values in its CSV. These scaling and reference choices are part of the interpretation.

Use `scripts/plot_x57_comparisons.py --figures 13 14 15 16 19` after all requested inputs have passing native case records. Add `--tables-only` for the four underlying CSV tables. The two sensitivity groups share one table and both 14 and 15 must be requested to publish it without the other figures. Times New Roman is embedded in the PDFs and the PNG output is 400 dpi. The five samples in the environment-audit area are marked as synthetic layout tests.

- A watertight and nonintersecting shell can still underresolve a blunt trailing edge. At z=3.800848 m, the iso45 input lost material across x=0.246–0.261 m while the CAD remained continuous. We restored a closed CAD loft from 54 probes at 9 span stations and 6 aft chord locations. The coarse 38 mm-span-step candidate recovered all 54 with a maximum thickness error of 0.664 mm. Report actual native wall geometry after meshing separately. Independent horizontal-tail solids preserve the measured 4.69 mm hinge gap. Local gap restoration is checked across 81 stations, including the last CAD-intersecting sponson station and the first open station.


### F-drive recovery and expanded stress outputs

Decision recorded 2026-11-23T06:10:21-08:00. P0, P1 and Figure 1 retain their accepted artifacts. The original first Coarse pilot exceeded its target, and the archive contained no reloadable volume mesh. The restored clearance surfaces passed 81 CAD section checks with maximum errors of 0.9473 mm, 0.4113 mm, and 0.4719 mm for Coarse, Medium, and Fine. Their 54 rear-wing thickness points and 7 hinge-gap stations also passed. Separate checks of the completed volume boundary and the Fluent solver mesh are required. Three native size fields have been produced for the subsequent Poly-Hexcore runs.

The launcher now attaches the suspended native Fluent process to a Windows kill-on-close Job Object before letting it run. A single process lock protects the Student seat. The resume scanner follows the native data file's saved case name, matches pressure cell ID ranges, and checks that both files can be read. The local paired-file check was exercised on the existing software fixture. This validation produced no aircraft CFD results.

The current figure contract comprises 22 dual-format figures, 22 three-dimensional renders, 19 structured tables/files and native Fluent submission archives. The structural field export includes both shell faces, von Mises, principal stresses, maximum shear, displacement and the ratio of yield to computed von Mises stress. Static, rolling and optimized operating conditions must each use their own aerodynamic loads. Use a common engineering scale for global safety maps and disclose the actual maximum stress and minimum computed safety factor. The shared plotting functions export 400 dpi and embed Times New Roman, including mathematical text. A scratch PDF verified the regular, bold, and italic font subsets. Scientific Colour Maps is installed in the F-drive virtual environment (cmcrameri distribution 1.10). [Scientific colour maps](https://doi.org/10.5281/zenodo.24343380). [Ansys Mechanical APDL element theory for SHELL181](https://ansyshelp.ansys.com/public/Views/Secured/corp/v252/en/ans_thry/thy_el181.html).

### F-drive restoration of propulsion, convergence and field diagnostics

The original STL hash and all 21 static thrust/torque calibration pairs were reproduced with the restored BEMT script. The six HLPs use a near-static extrapolation of NASA’s 4,800 rpm deployed-propeller map followed by similarity scaling. At nominal speed HLP-1 is 402.833 N and 26.710 N m. The CAD-based wingtip trim gives 1,549.055 N and 127.500 N m. These are actuator inputs. Each accepted production grid requires separate native source-volume integrals.

The auxiliary zero-speed medium-grid branch starts from the accepted nominal case, resets velocity and gauge pressure to zero and temperature to 288.15 K, and verifies the original grid connectivity, native field extrema, wall forces, opening fluxes, and all seven sources. It supplies the static-lift baseline and the four-condition propulsion interaction. The nonzero RPM regression and the 18-case comparison exclude it. The native 12-cell fixture rejected a deliberate velocity perturbation of 0.05 m/s even when its report still asserted zero.

The native field path checks case/data pairing, three velocity components, pressure, cell IDs and volume-centre locations after restart. An extracted static-pressure, turbulence-model or velocity-gradient field enters a figure only through an accepted numerical endpoint. The bounded circulation diagnostic integrates signed axial vorticity over the actual fluid portion of the fixed wingtip shaft-centred 2R by 2R window. Upper-wing wall-law traces cross native cell faces along local surface normals, ending at a physical boundary. Data preparation scripts retain the native or derived provenance, the reference viscosity, and the density source. All published-flight figures await accepted project CFD and FSI evidence.

The signed native volume audit follows Fluent’s c0-inward face convention and evaluates face-fan volumes about a local cell reference for precision in thin prisms. It recovered 12 m³ on a 12-cell box and 1 m³ on the 2,961-cell native meshing fixture. Reversing all face loops correctly flagged every box cell. Independent geometric orthogonality is used to locate defects. The archived mesher and solver-standard orthogonal-quality reports, tied to the production mesh hash, govern acceptance.

### Unequal grid spacings and alternating refinement differences

The CFD and shell-grid calculations use the actual spacings and the signed ratio of adjacent grid differences. Raw Celik apparent order, fine and medium Richardson projections, approximate and extrapolated relative errors, grid convergence indices and the asymptotic ratio are retained. The project troubleshooting manual, section 9, calls for a separate formal second-order estimate with a 1.25 safety factor and a half-range interval for alternating differences or apparent orders outside 0.5 to 3.0. Reported uncertainty bars cover the raw estimate, formal estimate and observed range. A repeated difference or zero fine-grid reference leaves unresolvable quantities empty. The final quantitative check reconstructs the flow spacings from measured volumes and counts, compares the force series, and tests both raw and reported uncertainties against the project thresholds. [Celik et al., Journal of Fluids Engineering (2008)](https://doi.org/10.1115/1.2960953)

### Native pause checkpoints and manual §1 Fine evidence

Production solver journals save an initialized case/data pair before their first iteration, retain paired autosaves every 50 iterations, and use the Windows Fluent 2025 R2 working-directory file `exit-fluent.txt`. The supervisor polls the gate before treating a journal interruption as an error and records the native restart kind, files, provenance and force-termination status in `managed_stop.json`. Surface meshes can restart completed meshing preparation. The interior of a single poly-hexcore generation command has no recoverable volume state before the first native volume write.

The offline supervisor regression exercised four return codes and cleanup using a Windows child process and existing native 12-cell CFF files. Fifteen installed 25.2 API bindings and the generated first coarse journal passed offline checks. A live Fluent interruption during production iteration remains a runtime verification item. The 2025 R2 source is [Fluent User’s Guide §4.4](https://ansyshelp.ansys.com/public/Views/Secured/corp/v252/en/flu_ug/flu_ug_checkpointing.html).

Normal P2 publication uses `verify_mesh_level.py --publish` and `verify_mesh_ladder.py`. The preauthorized Fine exception uses `verify_fine_budget_exception.py register INITIAL_QA TRIAL_CONFIG` before generating the one refinement, followed by `admit` only when its measured CFF exceeds 1,045,000 cells. The initial candidate must have 960,000–1,019,000 cells, native standard minimum orthogonal quality above 0.15, acceptable measured clearances and all remaining Fine mesh checks. Registration binds the input, geometry and size field. The implementation treats a quoted “approximately 3%” refinement as a 2–4% reduction for changed BOIs with remaining BOIs unchanged, and preserves wing inflation. `solver_admissible` permits the physical trial. P5 subsequently requires the matched accepted case/data, native area-weighted wing mean y+ from 0.5 through 1.2 and p95 below 2.5 before final `passed`. No production exception or result has been registered by the offline tests.


### 2026-11-23 P2 净空、棱柱及近滑流预算

Coarse C09 在 Fluent 中生成 270,260 个单元。首次报告 27,700 个单元的逆正交质量超过 0.95，监控按规则退出。C10 将八叉树六面体、棱柱和过渡单元单独保存在 `02_mesh/coarse/f_scoped_primary_10/coarse_before_dual.msh.h5`。该中间文件的 501,616 个单元包含 122,988 个六面体和 79,202 个楔形单元。原生日志先后报告 58,066 和 38,706 个单元超过相同阈值。独立重建面扇体积得到零个非正体积。几何定位的 25,287 个余弦值低于 0.05 的单元中有 17,045 个楔形、5,036 个四面体和 3,206 个金字塔。两种质量计数采用不同定义。原生日志、单元类型、坐标和层号保存在该候选目录。监控器今后保留首次出现的超限值，并同时记录原生程序和监管器各自的返回码。

C11 的修复使内翼后缘与 HLP-6 短舱三处原生顶面异常位置对应的表面三角形形状指标从 0.050、0.013、0.030 升至 0.833、0.182、0.901。第 4 层使用正交质量作为层内光顺指标时，四个 MPI rank 均报告 SIGSEGV。C12 沿相邻细长面传播边长过渡，将机翼表面低于 0.01 的三角形从 6 个降至 0 个，并恢复受支持的 ICEM 层内光顺设置。234 个机翼探针和 294 个短舱探针的 CAD 包络最大偏差分别为 0.485 和 0.592 mm，81 个净空站位最大偏差为 0.947 mm。体网格仍接受独立求解器标准正交质量验收。

Fine 的强制总数区间为 1,020,000–1,044,000，本次执行不援引过往的降档例外。若 35–45 mm 要求覆盖整个长方体，0.24 × 1,044,000 = 250,560 的区域预算与几何容量冲突。将边界向内收缩 78 mm，扣除向外扩展的五个实体包围盒和七个桨盘包围盒后，仍剩 24.618574 m³，至少需要 270,163 个边长 45 mm 的八叉树单元。可复核输入与排除边界见 `02_mesh/fine/near_wake_capacity_bound.json`。该下界仅适用于整盒逐单元尺寸上限。盒内真实滑流管与整盒的尺寸统计应分别如实给出，整盒预算继续按原验收器实测。

按 [Fluent 2025 R2 棱柱生成说明](https://ansyshelp.ansys.com/public/views/secured/corp/v252/en/flu_ug/tgd_user_prism.html) 核对了首层高度、法向及局部层压缩的作用。

### Coarse 原生导入表面的 CAD 复测

C14 的 Fluent 自动表面质量改善将 46,146 个三角面改为 24,978 个，81 处净空检查有 4 处开闭状态错误，最大净空偏差 53.807 mm。已淘汰。C15 保留原生导入表面并单独核验，81 处净空开闭全部一致，最大偏差 0.947 mm，234 处翼根后缘最大偏差 0.485 mm，294 处短舱最大偏差 0.592 mm。证据在 02_mesh/coarse/f_guided_preserve_15/native_surface_cad_audit.json。该结果只验收表面。

复测三档表面的局部棱柱底面。Coarse 机翼形状指标低于 0.10 的三角形由 329 个减至 114 个。Coarse、Medium、Fine 分别有 37,332、55,476、78,482 个实体壁面三角形，均通过闭合、自交、81 处净空和 652 处尾翼尖 CAD 复测。三档尾翼尖包络最大误差均为 0.592 mm。

若 Fine 翼尖桨盘的 12 mm 是笛卡尔六面体的逐单元边长上限，0.635904 m 的径向测线至少穿过 53 个单元，而 32 层上限要求平均径向弦长至少 19.872 mm。几何输入与条件见 02_mesh/fine/tip_disk_radial_capacity_bound.json。

C15 在 20.0 分钟内完成并保存真实 Poly-Hexcore，296,214 个单元，最小体积 1.072129e-16 m³，独立 CFF 面锥积分检测零个非正体积。Fluent 网格检查仍失败，6 个短舱壁面与 8 个内部面左手，最小正交质量 0，原生直方图 21,858 个单元超过逆正交质量 0.95。最差逆正交质量为 1.5738412，位置 (0.141047, −0.012568, 3.761614) m。机翼棱柱面积覆盖 80.504%，可追踪最长单基底柱 10 层，未达 12 层。C15 淘汰，未用于任何流场计算。精确直方图、逐壁面覆盖和 HDF 坐标见 02_mesh/coarse/f_guided_preserve_15。

C16 在 FTM 导入时实测发现坐标跨度比源网格大 1,000 倍。修正尺度后用原生 HDF5 对照 48.0 × 19.7 × 20.0 m 的外流域，并通过实际机翼、短舱、净空及尾翼探针。原始材料点包面曾遗漏 55 个净空截面。已用原生 append-mesh 和 volumetric-regions/compute 在工作流副本内重新装配 actual external_fluid，整个区域的 11 个 HDF5 原生面区 ID 为 6930–6940。合规区域证据为 02_mesh/coarse/f_registered_ftm_16/conformal_region_cad_audit.json。该证据用于几何，体网格和求解尚未签出。

<!-- BEGIN VERIFIED COURSEWORK RESULTS -->
## Verified coursework results

The nominal Fine solution gives a full-aircraft vertical airframe force of **-170.150 N** and an airframe drag of **194.925 N**. Positive vertical force points upward. The wing contributes 153.322 N. The measured gross static thrust is 7931.545 N. The axial force available after airframe drag is 7736.620 N. [Force summary](data/summary_metrics.json)

On a matched Medium mesh, the signed static lift increment between unpowered equilibrium and nominal powered operation is **-160.679 N**. The endpoints are 0.000 N and -160.679 N. The through-origin square-speed fits have centered R² of 0.998485 for lift increment and 0.999456 for drag. [RPM sweep](data/rpm_sweep.csv)

### Conditions and method

The baseline represents the start of taxiing at sea level and zero free-stream speed. Fluent uses ideal-gas air at 101325 Pa and 288.15 K, with a dynamic viscosity of 1.789 × 10⁻⁵ Pa s. Each wing carries six 5400 RPM high-lift propellers and one 2700 RPM wingtip propeller. Seven annular volume sources on the starboard half-model impose calibrated axial thrust and swirl. The symmetry plane represents the port half. The stationary runway and external pressure boundaries represent the static ground condition. The nominal turbulence closure is k–ω SST. Mesh and solver settings are preserved in the native submission.

The static coefficient reference uses disk-induced dynamic pressure 305.94 Pa and full wing area 6.1934 m². On this convention the Fine solution gives C_L = -0.089800 and C_D = 0.102875. [Actuator inputs and native disk integrals](data/actuator_disk_model.json)

### Numerical verification

| Grid | Fluid cells | Minimum orthogonal quality | C_L | C_D |
|---|---:|---:|---:|---:|
| coarse | 292,178 | 0.0061 | -0.089665 | 0.096669 |
| medium | 570,033 | 0.0102 | -0.084801 | 0.102528 |
| fine | 952,382 | 0.0004 | -0.089800 | 0.102875 |

Fine-grid wing y⁺ is 141.816 by area-weighted mean and 980.816 at P95. Fine-grid GCI is 211.101% for vertical force and 0.057% for drag. The documented uncertainty bound is 211.101% and 6.033%, respectively. [Mesh and GCI](data/asme_vv20_gci.json) · [Convergence history](data/convergence_qa.csv)

### Suction and swirl

The lowest Fine-grid wing-face pressure is -3379.235 Pa gauge, C_p = -11.045557. The starboard face centroid is (-0.34905, 0.11486, 1.49716) m, at 2z/b = 0.31067 and x/c = 0.04371. The same-mesh swirl ON minus OFF change in full-wing lift is +136.899 N over the inboard segment and +133.786 N over the tip segment. The boundary is the inboard edge of the wingtip disk. [Spanwise loading](data/spanwise_loading.csv) · [Wing pressure sections](data/wing_cp_sections.csv)

### Design and stress interpretation

Among the five computed section designs the maximum change in section lift coefficient is +1.128851 for 30° slotted flap, with ΔC_D = +0.575520. All section comparisons use the HLP-3 slipstream from the accepted Fine solution and the clean blown section as baseline. The three-dimensional 10° HLP-vector change gives ΔC_L = -0.474218 and ΔC_D = -0.062705 against the nominal Medium aircraft. The dimensional section forces are reported per unit span. [Design comparisons](data/design_optimization_results.csv) · [Eighteen-case study](data/expanded_experiments_summary.json)

The structural calculation uses static one-way pressure and shear transfer into equivalent SHELL181 component models. Material, shell thicknesses, joint representation and supports are modeled assumptions. Peak element-average von Mises stress is 277.2 MPa. The area-weighted 99th percentile is 50.23 MPa, the nominal yield safety factor is 1.814, and the mean wingtip patch displacement magnitude is 28.81 mm. Structural discretization and CFD-load refinement studies passed their recorded 3% gates. [Structural convergence and assumptions](data/fsi_structural_stress.json) · Each stress CSV row describes one native sample. The named quantity, unit and value give its principal observable. The sample_fields_json column contains the other source-specific measurements, including both shell surfaces, location and sampling identifiers. [Stress fields](data/stress_and_bl_profiles.csv)

The report author can use Figures 2–3 for mesh and force convergence, 4–11 for native flow and surface results, 12–16 for propulsion and design comparisons, and 17–22 for fluid and structural stress, flow topology and the combined design assessment. Native 3D views 4–5 show the propeller slipstreams and wingtip vortex paths. Views 6–8 show top and bottom pressure and velocity streamlines. [Figure directory](figures/) · [Native 3D views](fluent_renders/) · [Reloadable Fluent attachments](ansys_submission/)

### Model and verification sources

The HLP calibration uses NASA propulsion data. The cruise calibration and section polar underpin the wingtip actuator estimate. The audit contains the extrapolation and similarity assumptions. [NASA HLP data](https://ntrs.nasa.gov/citations/20240014295) · [NASA cruise propeller data](https://ntrs.nasa.gov/citations/20240006496) · [OpenFAST section polar](https://raw.githubusercontent.com/OpenFAST/r-test/main/glue-codes/openfast/5MW_Baseline/Airfoils/NACA64_A17.dat)

The three-grid procedure uses measured fluid volumes and unequal refinement ratios. [Celik et al. (2008)](https://doi.org/10.1115/1.2960953)
<!-- END VERIFIED COURSEWORK RESULTS -->
