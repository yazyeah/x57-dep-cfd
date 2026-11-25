# X-57 DEP CFD Coursework — 顶刊发表级评估准则、Student 版极限细化网格规划与全量拓展实验方案

> 本规范是整个 `D:\FEA Coursework\Workspace` 的最高技术规格书，融合 **ASME V&V 20-2009 / Celik et al. (2008)**、**AIAA DPW/HLPW** 与 **NASA X-57 Mod IV 吹气机翼文献基准**，并在 **ANSYS Fluent 2025 R2 Student（编译级硬上限 `< 1,048,576` 单元、`-t4` 核）** 约束下，将三维精细网格、拓展物理实验、高升力优化 CFD 与可视化深度全面拉满。

---

## 一、关于“能否做到 140 万单元”与 Student 版绝对极限细化规划

1. **许可硬红线（已在 S0 实测确认）**：
   - ANSYS Fluent 2025 R2 Student 编译级上限为 **`< 1,048,576` 单元**（S0 实测 `1,048,577` 单元被求解器直接拒载，因此单算例无法超过 `1,048,575` 单元）。
   - 但本方案采用 **半机对称（×2）+ Poly-Hexcore 马赛克拓扑（~3× 等效四面体精度）**：
     - 半机顶格 **`940,000 – 1,044,000` 单元** = **全机 `1,880,000 – 2,088,000` 单元等效**（远超 140 万全机规模！），等效全机四面体精度约 **500~700 万单元**！
2. **Fine 网格顶格极限（89.6%–99.6% 许可利用率）5 分区精细预算表**：
   - 三套系统加密网格梯度：
     - **Coarse**：`280,000 – 380,000` 单元
     - **Medium**：`560,000 – 680,000` 单元
     - **Fine**：**`940,000 – 1,044,000` 单元**。按各级实际半域流体体积 $V_i$ 与原生单元数 $N_i$ 计算 $h_i=(V_i/N_i)^{1/3}$，要求 $r_{32}=h_\mathrm{coarse}/h_\mathrm{medium}\ge1.18$ 且 $r_{21}=h_\mathrm{medium}/h_\mathrm{fine}\ge1.15$。规划下一级时固定已签出网格的单元数与实测体积，先筛选可行计数组合。
   - **Fine 网格精细单元预算分配（各区间含两端，以每套实测总单元数为分母）**：
     | 区域 | 局部尺寸 / 边界层配置 | 目标单元占比 | 估算单元数 | 气动目的 |
     |---|---|---|---|---|
     | **1. 吹气主翼 (`wall_wing`) + 棱柱层** | 表面 `12–18 mm`，曲率角 `10°–12°`，**18 层棱柱**（首层 `1.2e-5 m`，增长率 `1.16–1.18`） | **28%–42%** | 263,200–438,480 | 锁定 $y^+ \approx 0.5\text{–}1.0$、精准解析前缘最大吸力峰与上下翼面压差 |
     | **2. 7 个桨盘加密 BOI** | HLP 盘 `7–9 mm`、翼尖桨 `10–14 mm`（50 mm 盘厚内 **轴向 `>= 6` 层**、**径向 `>= 22` 层下限**；大直径翼尖桨 `WT-1` 达 `40–55` 径向层为更高精度，直接达标） | **15%–25%** | 141,000–261,000 | 精准施加 Goldstein 径向推力与切向旋流，离散积分误差 `< 0.5%` |
     | **3. 吹气机翼与近滑流管 BOI** | $x \in [-1.0, +2.8], y \in [-0.85, +0.95], z \in [0.35, +5.65]\text{ m}$：盒内**真实吹气滑流管核心区**六面体 **`35–45 mm`**，外围非核心边角平滑过渡至 `50–65 mm`（以 `17%–28%` 占比为准） | **17%–28%** | 159,800–292,320 | 低耗散捕捉射流收缩、桨间剪切层、整流罩净空与翼尖涡核 |
     | **4. 短舱/机身/整流罩/尾翼 + 中尾流** | 中尾流 `80–110 mm`，其余壁面 **14–16 层棱柱** | **12%–24%** | 112,800–250,560 | 准确解析短舱-机翼干扰、地面效应与平尾下洗 |
     | **5. 外围空旷远场盒** | 增长率 `1.22`，`MaxSize = 2.0–2.5 m` | **0%–6%** | 0–62,640 | 绝不浪费宝贵单元在静止远场空气中 |

3. **P2 原生体网格与单独提质**。GenerateTheVolumeMeshFTM 的 `OrthogonalQuality` 使用 `0.05`，生成器参数检查为 `0.0 <= quality <= 0.10`。原始网格先验实际单元数，落入本级窗口后才运行 `improve_raw.jou`。单独提质使用 `auto-node-move` 的 inverse-OQ 阈值 `0.85`、迭代 `5` 次。独立求解器重载的标准最小正交质量必须 `>0.10`，推荐 `>=0.12`；负体积数必须为零。单次体网格生成日志连续 35 分钟无新行时立即中止诊断。
   - 每级保留一个流体域与 11 个物理边界、Poly-Hexcore 核心及五个壁面全深度边界层。整流罩所有 CAD 对应净空的误差上限为 Coarse 3 mm、Medium 3 mm、Fine 5 mm（含上限）。Fine 七盘轴向与径向最小层数分别为 6 与 22，Student 求解器实际载入单元数必须严格低于 1,048,576。单级通过后固定，继续后续级次。

---

## 二、一键停止支持（点击 Codex 暂停键即刻秒停）+ 可见 Ansys GUI

1. **点击 Codex 暂停输出键 = 即刻干净停机**：
   - `scripts\run_fluent_managed.py` 已内置 **Windows Win32 Job Object（`JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`）+ OS 信号捕获**：用户点击 Codex 界面暂停输出键后，Windows 内核会瞬间结束全部 `fluent.exe` / `fl_mpi2520.exe` / `cx2520.exe` 进程树，绝不残留僵尸进程，也无需再输入“暂停”提示词！
   - **高频自动存档铁律**：所有求解 journal 必须配置 **`/file/auto-save/data-frequency 50`**（保留最新 2 份 `.cas.h5`/`.dat.h5`）并开启 `(set! checkpoint/exit-filename "exit-fluent")` 和 `/file/confirm-overwrite no`，确保任何时刻一键中断最多只损失 2~4 分钟迭代，下次发一句“继续”即可从最新自动存档无缝续算！
2. **可见 Ansys Fluent 桌面 GUI**：
   - 所有正式网格（Coarse/Medium/Fine）、求解与 3D 渲染均通过升级后的 `run_fluent_managed.py` **默认打开可见 Fluent 桌面 GUI**，用户可实时观看网格、残差与升力监测图，并利用 RTX 4060 硬件 OpenGL 输出高清 3D 图！

---

## 三、四重全局强收敛 + ASME V&V 20 量化红线

1. **四重全局强收敛（所有算例硬门槛）**：
   - **力与力矩全局稳态**：最后至少 **200~300 步** 内，$L_{\text{air}}$、$L_{\text{wing}}$、$D_{\text{air}}$ 与俯仰力矩 $M_z$ 连续两段 100 步均值漂移 `< 0.3%`（红线 `< 0.5%` 或 `< 0.5 N`），标准差 `< 0.3%`（红线 `< 0.5%` 或 `< 1.0 N`）；
   - **全域残差**：全二阶格式 + Warped-Face 梯度修正 + $k\text{-}\omega$ SST 曲率修正下，残差降 4~6 阶（动量/湍流 `< 1e-4`、能量 `< 1e-6`、连续性 `< 5e-4` 目标 / `< 1e-3` 红线且平稳）；
   - **全域质量守恒**：净质量通量误差 `< 0.1%`（红线 `< 0.5%`）；
   - **桨盘动量守恒**：全部 7 桨盘离散积分推力/扭矩与 BEMT 目标值误差 `< 0.5%`（红线 `< 1.0%`）。
2. **ASME V&V 20 / Celik (2008) 完整 6 步 GCI**：
   - 输出 `DELIVERABLES\data\asme_vv20_gci.json`：$r_{21}, r_{32}, p, \phi_{\text{ext}}, e_a, e_{\text{ext}}, \text{GCI}_{\text{fine}}, \text{GCI}_{\text{med}}, R_{\text{asymp}}$。

---

## 四、全量 18 算例拓展实验矩阵（覆盖全部任务书要求 + 顶刊级深度拓展 + 高升力实算优化）

| 组别 | 算例 ID | 配置与设置 | 科研/工程目的 |
|---|---|---|---|
| **A. 核心基线与网格/转速/旋流（6 算例）** | `coarse_rpm100` | Coarse (~330k), 100% RPM, Swirl ON | 三网格收敛 Level 1 |
| | `medium_rpm100` | Medium (~640k), 100% RPM, Swirl ON | 三网格 Level 2 + 全套拓展基线/热启动源 |
| | `fine_rpm100` | **Fine (`0.940M–1.044M` 顶格极限!)**, 100% RPM, Swirl ON | **主标杆流场 + 课程提交附件** |
| | `medium_rpm050` | Medium, 50% RPM (2700/1350), Swirl ON | 转速-升力标度律（50%） |
| | `medium_rpm075` | Medium, 75% RPM (4050/2025), Swirl ON | 转速-升力标度律（75%） |
| | `medium_rpm100_noswirl` | Medium, 100% RPM, Swirl OFF | 旋流剥离对照实验 |
| **B. 3D 气动推进深度拓展与鲁棒性验证（6 算例，Medium 热启动）** | `medium_rpm100_hlp_only` | 仅 6 副 HLP 开启，翼尖桨关闭 | **动力耦合分解（1/2）**：剥离 HLP 吹气独立贡献 |
| | `medium_rpm100_wt_only` | 仅翼尖桨开启，6 副 HLP 关闭 | **动力耦合分解（2/2）**：量化翼尖桨贡献与非线性干扰项 |
| | `medium_rpm100_alt_swirl` | 相邻 HLP 交替反旋（NASA Mod IV 后期构型） | 旋向构型优化对比（同向内侧上行 vs 交替反旋） |
| | `medium_rpm100_takeoff_v10` | 滑跑前飞速度 $V_\infty = 10\text{ m/s}$ + 移动跑道 $10\text{ m/s}$ | 静推($V=0$)向起飞滑跑过渡的升力增强演化 |
| | `medium_rpm100_oge` | 移除跑道壁面（改为开放压力边界） | **地面效应量化（IGE vs OGE）** |
| | `medium_rpm100_rke` | Realizable $k\text{-}\varepsilon$ (Enhanced Wall Treatment) | **湍流模型敏感性验证**（AIAA 顶刊必备！） |
| **C. 3D + 超精细 2D 高升力改型实算优化（6 算例）** | `medium_opt_hlp_vector10` | 3D Medium 网格：HLP 推力矢量下偏 $10^\circ$（或桨轴抬升优化） | **3D 推进布局优化实证**：消除翼下吸力、实现大幅正向静态增升！ |
| | `opt2d_01_clean` ~ `opt2d_05_camber_opt` | 基于 CAD 真实 `z=2.041 m`（HLP-3 剖面）翼型 + HLP-3 真实入口滑流，Fluent 2Ddp 超细网格（~100k 单元，$y^+<0.5$）对比：**Clean 基线 / +15° 襟翼 / +30° 开缝襟翼 / 前缘缝翼+30° 襟翼 / +3% 弯度改型** | **用真实 Fluent CFD 数值与流场图量化回答任务书全部改型建议（襟翼/缝翼/弯度）**，直接对标 NASA X-57 Mod IV 文献！ |

---

## 五、全量顶刊级交付物清单（36 套视觉成果 + 19 份结构化数据 + Ansys 提交附件）

全部输出至 `D:\FEA Coursework\Workspace\DELIVERABLES\` 并通过 `scripts\verify_deliverables.py`（退出码 `0`）。绘图风格必须严格遵循新增的 `skills\top-venue-scientific-visualization\SKILL.md`（融合 **AIAA *Journal of Aircraft* / JFM / Nature** 物理深度与 **CVPR / ICCV / NeurIPS** 多面板复合排版、`mark_inset` 局部放大、GCI 误差带、小提琴/雷达/Pareto/热力图与白底 PyVista/Fluent 高清渲染），并在需要时主动联网查找 `SciencePlots`/`tueplots`/`cmocean`/`PyVista` 最新绘图技巧（安装仅限 `D:\FEA Coursework\Workspace\.venv`）！

1. **20 套顶刊/顶会级复杂复合 Matplotlib / PyVista 科学图（`figures\`，每套 `400 DPI PNG` + `矢量 PDF`）**：
   - `fig01_geometry_and_domain` ~ `fig12_actuator_disk_verification_and_design_concept`（原有全部 12 套，升级复合排版与 `mark_inset` 放大框）
   - `fig13_propulsion_decomposition_and_synergy`（全开 vs 仅 HLP vs 仅翼尖桨耦合分解 + 交替反旋对比）
   - `fig14_ground_effect_and_takeoff_roll`（IGE vs OGE 地面效应对比 + $V=0 \to 10\text{ m/s}$ 滑跑过渡对比）
   - `fig15_turbulence_model_sensitivity`（$k\text{-}\omega$ SST vs Realizable $k\text{-}\varepsilon$ 翼面 $C_p$、速度剖面与力系数对比）
   - `fig16_highlift_design_optimization_cfd`（3D 推力下偏优化 + 5 种超细 2D 吹气翼型改型：流线、$C_p$ 曲线、$\Delta C_L / \Delta C_D$ 增益对比）
   - **`fig17_stress_convergence_and_fsi_structural`**（1-Way FSI ANSYS MAPDL `SHELL181` 应力网格收敛曲线+GCI、展向弯矩/扭矩/挠度分布、全机安全许用色标低应力蓝云图 + CVPR 风格 `mark_inset` 翼根/短舱根部局部应力集中放大图！）
   - **`fig18_wall_shear_and_reynolds_stress_fields`**（流体应力综合图：全机壁面切应力 $\tau_w$ 双尺度分布 + 尾流湍动能 $k$ 与雷诺切应力 $-\rho\overline{u'v'}$ 切片 + 4 站位总压系数 $C_{p0}$ 能量演化！）
   - **`fig19_multi_case_ablation_heatmap_and_radar`**（**CVPR/NeurIPS 标志性多维综合图**：多指标雷达图 + 高升力改型 $\Delta C_L$ vs $\Delta C_D$ Pareto 前沿 + 18 算例 × 10 核心 KPI 归一化消融与敏感性标注热力图！）
   - **`fig20_flow_topology_and_vortex_dynamics`**（**JFM/AIAA 标志性流动物理复合图**：涡环量 $\Gamma(x)$ 衰减 + 机翼边界层 $u^+(y^+)$ 对标理论壁面律 + 5 部件压力/$\tau_w$/$y^+$ 小提琴分布 + 7 桨盘后展向诱导迎角 $\alpha_{\text{ind}}(z)$！）
2. **16 张 Ansys Fluent / MAPDL / PyVista 原生 3D 高清渲染图（`fluent_renders\`，`>= 1920×1080` PNG，纯白学术背景）**：
   - `render01` ~ `render12`（原有全部 12 张：远场六面体、18 层边界层、整流罩与桨盘加密、全机 3D Pathlines 滑流、翼尖涡 Pathlines、上下表面压力云图、三维流线、Q-criterion 涡结构、表面 $y^+$ 与油流、IGE/OGE 对比、高升力优化流场对比）
   - **`render13_fluent_wall_shear_stress_3d.png`**（全机 3D Fluent 壁面切应力 $\tau_w$ 云图，整体低应力冷蓝色 + 吹气前缘细节）
   - **`render14_fluent_tke_and_total_pressure_3d.png`**（全机 3D 湍动能 $k$ / 总压滑流能量核三维可视化）
   - **`render15_fsi_von_mises_stress_global_3d.png`**（全机 3D 1-Way FSI 结构 von Mises 等效应力云图——工程许用安全色标下整体收敛为低应力冷蓝色，标注安全系数 $\text{FoS} \gg 20$！）
   - **`render16_fsi_stress_zoom_and_deformation_3d.png`**（翼根与短舱吊架局部自适应色标应力集中特写 + 放大弹性变形叠加图）
3. **19 份结构化数据（`data\`：7 JSON + 12 CSV）**：
   - JSON：`environment_and_license.json`, `geometry_audit.json`, `actuator_disk_model.json`, `summary_metrics.json`, `asme_vv20_gci.json`, `expanded_experiments_summary.json`, **`fsi_structural_stress.json`**
   - CSV：`mesh_convergence.csv`, `rpm_sweep.csv`, `yplus_stats.csv`, `wing_cp_sections.csv`, `spanwise_loading.csv`, `convergence_qa.csv`, `component_force_breakdown.csv`, `propulsion_decomposition.csv`, `sensitivity_ige_roll_turb.csv`, `design_optimization_results.csv`, **`stress_and_bl_profiles.csv`**, **`ablation_kpi_matrix.csv`**
4. **Ansys 提交附件（`ansys_submission\`）**：顶格 Fine 网格与收敛算例 `X57_DEP_fine_rpm100.msh.h5`、`X57_DEP_fine_rpm100.cas.h5`、`X57_DEP_fine_rpm100.dat.h5`（验证可重开）+ `DELIVERABLES_MANIFEST.json` + `handoff_notes.md`。

---

## 六、精细化 12 阶段里程碑（每阶段记录到 `logs\STAGE_REPORTS.md`，全自动跑到 P12 完工）

- **P0 & P1**：许可审计 & 几何/BEMT 标定（**已完成**）
- **P2**：Coarse (~330k) / Medium (~640k) / **Fine (`0.940M–1.044M` 顶格 5 分区规划)** 三套网格（可见 GUI，约 50–90 min）
- **P3**：`coarse_rpm100` 全局收敛 + 单步速度与 ETA 标定（约 25–45 min）
- **P4**：`medium_rpm100` 全局强收敛（约 55–110 min）
- **P5**：顶格 **`fine_rpm100` (0.940M–1.044M 单元)** 全局强收敛 + 完整 ASME V&V 20 六步 GCI & $y^+$ 审计（约 1.8–3.5 hr）
- **P6**：`medium_rpm050` & `medium_rpm075` 转速平方律扫描（约 50–100 min）
- **P7**：`medium_rpm100_noswirl` 旋流对比（约 25–50 min）
- **P8（拓展 1）**：动力分解（`hlp_only`, `wt_only`）+ 交替反旋（`alt_swirl`）（Medium 热启动，约 60–110 min）
- **P9（拓展 2）**：地面效应（`oge`）+ 起飞滑跑过渡（`takeoff_v10`）+ 湍流敏感性（`rke`）（Medium 热启动，约 60–115 min）
- **P10（拓展优化 + 1-Way FSI 应力收敛）**：3D 推进优化（`medium_opt_hlp_vector10`）+ 5 套超细 2D 吹气翼型高升力改型 CFD + **ANSYS MAPDL `SHELL181` 1-Way FSI 三套网格结构应力收敛验证**（约 55–95 min）
- **P11（顶刊/顶会级全量可视化）**：导出全部真实流体与应力数据 + 生成 **20 套复杂复合学术图（PNG+PDF）** + **16 张白底 3D 高清渲染图**（约 70–115 min）
- **P12（验收打包）**：封装顶格 Fine Ansys 提交附件 + 完整清单与交接报告 + 跑通 `verify_deliverables.py`（退出码 `0`）（约 15–25 min）

*(全部 18 算例总剩余耗时预估约 9–14 小时，可随时直接点 Codex 暂停键分段运行，5 天期限内游刃有余！)*
