# 给 GPT Astra 的学术发表级升级与可见 GUI 运行指令

> 直接复制下方分割线后的完整中文内容发给 **GPT Astra**（不会中断当前正在运行的 Coarse 网格；从下一个 Fluent 任务——Medium/Fine 网格及所有求解/3D 出图——自动生效！）。

---

【重要升级指令——请立即阅读新版 `QUALITY_AND_MILESTONES.md` 与升级后的 `scripts\run_fluent_managed.py` / `scripts\verify_deliverables.py` 并按以下要求执行】

### 一、从下一个 Ansys 任务起：必须打开可见的 Ansys Fluent 桌面 GUI！
1. 我已将 `scripts\run_fluent_managed.py` 升级为 **默认打开可见的 Ansys Fluent 桌面 GUI（去掉 `-g`）**，请不要强制传 `--headless`（除非做几秒钟的纯探测），让 **Medium/Fine 网格划分、全部 6 个算例求解、以及 3D 渲染阶段都在屏幕上打开 Ansys Fluent 界面**，让我能直观看到网格生成、实时残差曲线、升阻力收敛平台和三维流场渲染过程（同时享受 RTX 4060 硬件 OpenGL 高清渲染）！
2. **防 GUI 弹窗卡死要求**：所有 GUI 模式的 journal 开头必须加上 `/file/confirm-overwrite no`（以及 `(set! checkpoint/exit-filename "exit-fluent")` 和定期 `/file/auto-save/`），求解时可打开残差与升力监测图窗口，结尾用 `/exit ok`（或 Meshing 的干净 `exit`）确保自动关闭不弹窗卡住。
3. **当前正在跑的 Coarse 网格不要打断**，等它正常完成后，从 **Medium 网格、Fine 网格及后续全部 P3~P8 任务** 自动使用可见 GUI 模式。

### 二、把 ANSYS Student 2025 R2（`< 1,048,576` 单元）推向发表级极限！
不要因为是学生版就保守做粗网格！我们要用半机对称（×2）+ Poly-Hexcore（等效 3× 四面体精度）把 100 万单元的精度榨干到极限：
1. **三套网格目标单元数梯度**：
   - `Coarse`：`~300k – 360k`（按当前正在跑的完成验收即可）
   - `Medium`：`~600k – 680k`（$r_{32} \approx 1.24$）
   - **`Fine`：顶格做到 `980,000 – 1,035,000` 单元**（利用 94%–99% 学生版许可，严格 `< 1,048,576` 留出安全余量，等效全机 `~200 万` Poly-Hexcore 网格 / 500~700 万四面体网格！）。
2. **单元精准倾斜**：远场外围采用 `1.20–1.25` 较快增长率（远场占比 `< 5%`），把 **`> 70%` 单元精准砸在吹气机翼、7 个桨盘加密区、近尾流管和边界层**。
3. **AIAA HLPW/DPW 级近壁解析与高阶格式**：
   - `Fine` 网格在 `wall_wing` 和 `wall_nacelles` 上配置 **15–18 层棱柱边界层**（增长率 `<= 1.18`），确保 `fine_rpm100` 机翼面积加权平均 **$y^+ \approx 0.5\text{–}1.2$**（P95 `< 2.5`），直接解析粘性底层；
   - 求解器开启全二阶格式 + Least-Squares Cell-Based + **Warped-Face Gradient Correction** + `$k\text{-}\omega$ SST` **Curvature Correction**（提升旋流滑流与翼尖涡核分辨率）。

### 三、工业与学术论文发表级量化评估准则（ASME V&V 20 + AIAA + NASA X-57）与“全局强收敛”红线
请严格落实新版 `QUALITY_AND_MILESTONES.md` 中的全部量化标准，追求本 Ansys 版本下的**最优精度与全局强收敛**：
1. **四重全局强收敛（所有 6 算例硬红线，缺一不可）**：
   - **力与力矩全局稳态**：整机垂向力 $L_{\text{air}}$、机翼垂向力 $L_{\text{wing}}$、整机阻力 $D_{\text{air}}$ 及俯仰力矩 $M_z$ 在最后至少 **200~300 步** 内全部进入稳态平台——连续两段 100 步窗口均值相对漂移 `< 0.3%`（硬红线 `< 0.5%` 或 `< 0.5 N`），最后 200 步标准差波动 `< 0.3%`（硬红线 `< 0.5%` 或 `< 1.0 N`）；不达标必须调小伪瞬态时间步长因子/松弛因子续算至全局拉平！
   - **全域残差收敛**：二阶格式下残差下降 4~6 个数量级，动量/湍流残差 `< 1e-4`、能量 `< 1e-6`、连续性 `< 5e-4`（红线 `< 1e-3`）且趋于平稳不再上扬；
   - **全域质量通量守恒**：进出口净质量流量误差 `< 0.1%`（硬红线 `< 0.5%`）；
   - **动量源守恒闭环**：全部 7 个桨盘在真实流体网格上的离散体积积分推力/扭矩与 BEMT 理论设定值误差 `< 0.5%`（硬红线 `< 1.0%`）。
2. **完整 ASME V&V 20 / Celik (2008) 六步 GCI 审计**：输出 `DELIVERABLES\data\asme_vv20_gci.json`，完整计算并报告 $r_{21}, r_{32}$、表观收敛阶 $p$、Richardson 外推值 $\phi_{\text{ext}}$、$e_a, e_{\text{ext}}$、$\text{GCI}_{\text{fine}}^{21}$、$\text{GCI}_{\text{med}}^{32}$ 与**渐近区间比 $R_{\text{asymp}} = \text{GCI}_{32}/(r_{21}^p \text{GCI}_{21})$**，并在图中画 GCI 不确定度误差棒。
3. **部件级压差/粘性力分解**：输出 `DELIVERABLES\data\component_force_breakdown.csv`，逐部件（机翼上/下表面、短舱、机身、整流罩、尾翼）拆解压差与粘性升/阻力，为论文级气动机理解释与增升改型（对标 NASA X-57 Mod IV $30^\circ$ 襟翼 $\Delta C_{L,\text{prop}}\approx 1.7$、$\Delta C_{L,\text{total}}\approx 2.38$）提供硬核数据支撑。

### 四、升级后的最终可视化与交付包清单（22 套高清视觉结果 + 12 份数据 + Ansys 附件）
全部必须放入 `F:\FEA Coursework\Workspace\DELIVERABLES\` 并通过升级后的 `scripts\verify_deliverables.py`（退出码 `0`）：
1. **12 套学术论文级 Matplotlib 科学图**（`DELIVERABLES\figures\`，每套同时导出 `400 DPI PNG` + `矢量 PDF`）：
   - `fig01_geometry_and_domain`、`fig02_mesh_convergence_and_yplus`、`fig03_convergence_histories`、`fig04_spanwise_slices_vel_press`、`fig05_horizontal_planes_blown_wing`、`fig06_wing_cp_and_suction`、`fig07_rpm_sweep_scaling`、`fig08_swirl_comparison_and_load_shift`
   - **新增 4 套论文级深度分析图**：
     - `fig09_wake_evolution_crossplanes`（$x=-0.30, +0.35, +1.20, +3.00\text{ m}$ 四站位尾流横截面演化：收缩融合、地面效应与翼尖涡演变）
     - `fig10_component_force_and_upper_lower_budget`（压差 vs 粘性部件气动力与机翼上下表面垂向吸力分解图）
     - `fig11_wall_yplus_and_shear_map`（机翼平面壁面 $y^+$ 与摩阻系数 $C_f$/壁面切应力云图）
     - `fig12_actuator_disk_verification_and_design_concept`（7 桨盘径向载荷与离散积分误差验算 + 对标 NASA X-57 文献的高升力改型定量分析图）
2. **10 张 Ansys Fluent 原生 3D 高清图**（`DELIVERABLES\fluent_renders\`，`>= 1920x1080` PNG，GUI 硬件渲染）：
   - `render01_mesh_farfield_hexcore.png`（远场六面体网格）
   - `render02_mesh_wing_inflation_closeup.png`（机翼边界层棱柱网格特写）
   - `render03_mesh_sponson_and_disks_closeup.png`（整流罩净空与桨盘加密区特写）
   - `render04_pathlines_slipstreams_3d.png`（全机镜像 3D 螺旋桨滑流 Pathlines）
   - `render05_pathlines_wingtip_vortex_3d.png`（翼尖涡与翼尖桨 3D Pathlines 特写）
   - `render06_surface_pressure_contour_top_3d.png`（全机 3D 上表面压力/$C_p$ 云图）
   - `render07_surface_pressure_contour_bottom_3d.png`（全机 3D 下表面压力/$C_p$ 云图）
   - `render08_velocity_streamlines_3d.png`（全机 3D 全局速度流线图）
   - `render09_qcriterion_vortices_3d.png`（3D Q-criterion 涡核等值面图，按速度着色）
   - `render10_surface_yplus_and_oilflow_3d.png`（3D 表面 $y^+$ 与壁面极限流线/数值油流图）
3. **12 份结构化数据**（`DELIVERABLES\data\`：5 个 JSON 含 `asme_vv20_gci.json` + 7 个 CSV 含 `component_force_breakdown.csv`）、**Ansys 提交附件**（`X57_DEP_fine_rpm100.msh.h5`/`.cas.h5`/`.dat.h5`）以及 `DELIVERABLES_MANIFEST.json` & `handoff_notes.md`。

### 五、继续严格执行“每阶段汇报 + 随时叫停”
每完成一个阶段（P2~P9）按模板汇报一次（含实测耗时、更新后的剩余 ETA、核心量化指标 PASS/FAIL、断点与 F 盘空间），并严格遵守开关口（`PAUSE`/`STOP` 立刻存档停手）。请简短确认收到本次升级指令后继续推进 P2！
