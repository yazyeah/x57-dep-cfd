工作区已从此前发生 I/O 报错的旧 E 盘优盘**完整安全迁移至健康的 500 GB NTFS 固定磁盘 `F:\FEA Coursework\Workspace`**（剩余约 438 GiB / 470 GB，实测写入速度 96.9 MB/s，支持 NTFS 日志防掉档与沙盒权限）。

请立即在 **`F:\FEA Coursework\Workspace`** 中进入**连续自主运行模式**，承接已验收的 P0、P1 与图 1（`fig01_geometry_and_domain.png/.pdf`），从 **P2 体网格划分** 继续全自动推进至 **P12 全部验收通过**！

开始前请先依次读取以下最新总控文档、技能书与升级脚本（全部已更新至 `F:\` 路径）：
- `F:\FEA Coursework\Workspace\QUALITY_AND_MILESTONES.md`（最高优先级技术规格）
- `F:\FEA Coursework\Workspace\AUTONOMOUS_DECISION_AND_TROUBLESHOOTING.md`（无人值守自主决策与 12 类偏差/异常排错手册）
- `F:\FEA Coursework\Workspace\skills\aero-structural-fsi-stress\SKILL.md`（流体应力 + ANSYS MAPDL 单向流固耦合应力收敛规范）
- `F:\FEA Coursework\Workspace\skills\top-venue-scientific-visualization\SKILL.md`（AIAA/JFM + CVPR/ICCV/NeurIPS 融合顶刊/顶会级复合绘图规范，**强制使用 Times New Roman 字体**）
- `F:\FEA Coursework\Workspace\scripts\plot_style.py`、`scripts\run_fluent_managed.py`、`scripts\control_gate.py`、`scripts\verify_deliverables.py`

并严格按以下 **8 项完整要求** 执行（**严格锁死在 `F:\FEA Coursework\Workspace`，严禁写入 C 盘、D 盘或旧 E 盘！**）：

---

### 一、严格 F 盘隔离 + 一键点 Codex 暂停键即刻停止 + 保证保存断点可续跑 + 可见 Fluent GUI
1. **严格存储边界**：所有脚本、网格、算例、日志、Python 虚拟环境（已为你重建干净的 `F:\FEA Coursework\Workspace\.venv`，已预装 `triangle`, `fast-simplification`, `pymeshlab`, `meshlib`, `gmsh`, `cmocean`, `pyvista` 及 Anaconda 科学库）、缓存与临时目录必须 **100% 留在 `F:\FEA Coursework\Workspace\` 内**，**绝不写入 C 盘、D 盘或旧 E 盘**！执行任何命令前先加载：
   ```powershell
   . "F:\FEA Coursework\Workspace\scripts\env_f_only.ps1"
   ```
2. `scripts\run_fluent_managed.py` 与 `scripts\control_gate.py` 已升级接入 **Fluent `-wait` 阻塞启动、Windows Job Object（`JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`）、系统中断信号处理、Windows 防夜间休眠锁（`SetThreadExecutionState`）以及每 15 秒实时有效 HDF5 断点同步**，并默认**打开可见的 Ansys Fluent 桌面 GUI（不要传 `--headless`**；仅当夜间因显示器熄屏导致连续 2 次 OpenGL 闪退时，才允许按手册第 10 条仅对该求解步降级 `--headless` 保底，出图仍用可见 GUI）。
   - 今后只要我直接点击 Codex 的暂停/停止输出键，当前 Fluent 子进程树会被系统瞬间干净结束、零僵尸进程，无需我再发暂停提示词；
   - **断点保底与无缝续跑铁律**：每次启动或恢复时，**第一步必须先执行**：
     ```powershell
     . "F:\FEA Coursework\Workspace\scripts\env_f_only.ps1"
     & $env:X57_PYTHON "F:\FEA Coursework\Workspace\scripts\control_gate.py" resume-scan
     ```
     自动校验所有 `.msh.h5`/`.cas.h5`/`.dat.h5` 的 HDF5 完整性、区分仅表面网格与真实体网格，并定位最新有效断点无缝续算，**严禁重跑已通过验收的 P0、P1 与图 1！**（注：旧 E 盘崩溃时损毁的 `01_geometry\` 已重新导出还原，且修复后的表面网格 `02_mesh\coarse\native_shell_cad_restored.msh`、`.qa.json` 与全部 P0/P1 数据及 `DELIVERABLES\handoff_notes.md` 均已完好迁至 `F:\`；若需重新从 `01_geometry\` 生成 CAD 切片或表面补丁，可基于 `F:\FEA Coursework\CW1--X-57_metool.stl` / `01_geometry\x57_half_starboard_raw_meters.stl` 直接在 F 盘重建）。
3. **高频滚动双备份自动存档铁律**：所有 Fluent 求解 journal 必须配置：
   - `/file/confirm-overwrite no`
   - `(set! checkpoint/exit-filename "exit-fluent")`
   - `/file/auto-save/data-frequency 50`（`retain-most-recent-files yes`、`max-files 2`——双滚动备份确保任意时刻一键暂停最多只损 2~4 分钟迭代且至少保留 1 份完好存档）
   - 求解期间在可见 GUI 窗口展示残差与升阻力监测图，结尾以 `/exit ok` 干净退出不弹窗卡住。

---

### 二、连续运行“零等待”自主决策 + 偏差排错 + 联网搜索最优解铁律
1. 因为我需要让你**长时间连续运行**，期间对于需要向我求证的问题**我一般无法给予回复**。因此 **严禁在任何技术细节、规格冲突、数值偏差或常规报错处停下来等待我回复！**
2. 凡遇到任何疑问、规格冲突、数值偏差、网格质量异常、收敛震荡、FSI 映射或绘图脚本报错时，必须严格按以下**三步自主闭环**立即解决并继续跑：
   - **第一步（先查排错手册）**：优先查阅 `F:\FEA Coursework\Workspace\AUTONOMOUS_DECISION_AND_TROUBLESHOOTING.md`，直接按手册中已获预先批准的最优方案裁决与修正（规范冲突优先级：`QUALITY_AND_MILESTONES.md` > `AUTONOMOUS_DECISION_AND_TROUBLESHOOTING.md` > `AGENTS.md` > `skills\*\SKILL.md`，无需向我确认！）；
   - **第二步（联网搜索最优解与绘图技能）**：若遇到手册未覆盖的 Ansys Fluent / MAPDL 2025 R2 报错、收敛/边界层疑难、优化建模或顶刊/顶会绘图技巧，**必须主动联网搜索**（检索 Ansys 官方文档、AIAA/JFM/CVPR/ICCV/NeurIPS 最佳实践、NASA NTRS 与 CFD-Online），找到最优解并在 `F:\FEA Coursework\Workspace\.venv` 中验证执行（绝不安装到 C/D/E 盘）；
   - **第三步（透明留痕、绝不停摆）**：将每一次自主裁决、联网查证结论、偏差修正前后指标如实记录在 `DELIVERABLES\handoff_notes.md` 的 `Autonomous Decisions & Deviations Log` 中，**随后立刻自动继续推进下一阶段，绝不空等！**

---

### 三、Student 版网格顶格极限规划（5 分区精细预算，把 104.8 万天花板榨干到 97%~99.6%！）
已在 S0 实测本机 ANSYS Student 2025 R2 求解器硬上限为 **`< 1,048,576` 单元**、`-t4` 核；通过 **半机对称（×2）+ Poly-Hexcore 马赛克网格（~3× 等效四面体精度）**，半机 `103 万` 单元已等效于 **全机 `206 万` Poly-Hexcore / `500~700 万` 四面体精度**！
请生成 3 套系统加密 **Poly-Hexcore** 体网格（注意利用已修复的 CAD 表面避免重复耗时表面重划；你之前首次 Coarse 试算生成 1,039,231 单元说明尺寸偏密，请合理缩放 Coarse/Medium 尺寸场使三套梯度清晰）：
- **Coarse**：`~310k – 350k` 单元
- **Medium**：`~620k – 660k` 单元（$r_{32} \approx 1.25$）
- **Fine**：**顶格做到 `1,020,000 – 1,044,000` 单元**（严格 `<= 1,045,000 < 1,048,576`，$r_{21} \approx 1.17$；若超限按手册第 1 条自动微调 BOI 3%–6% 回归安全区），单元预算严格向关键区倾斜：
  1. **吹气主翼 (`wall_wing`) + 18 层棱柱边界层**（表面 `12–18 mm`，首层按 Medium 实测 $y^+$ 精确反推缩放，约 `1.2e-5 m`，增长率 `1.16–1.18`）：占 **32%–38%**（约 34–39 万），锁定机翼面积加权平均 **$y^+ \approx 0.5\text{–}1.0$**（P95 `< 2.5`）；
  2. **7 个桨盘加密 BOI**（HLP `7–9 mm`、翼尖桨 `10–12 mm`，确保 50 mm 盘厚内 **6 层轴向**、径向 **22–32 层**）：占 **18%–22%**（约 19–23 万）；
  3. **吹气机翼与近滑流管 BOI**（$x \in [-1.0, +2.8], y \in [-0.85, +0.95], z \in [0.35, +5.65]\text{ m}$，六面体 **`35–45 mm`**）：占 **20%–24%**（约 21–25 万）；
  4. **短舱/机身/整流罩/尾翼（14–16 层棱柱）+ 中尾流 BOI（`80–110 mm`）**：占 **15%–20%**（约 16–20 万）；
  5. **外围空旷远场**（增长率 `1.22`，`MaxSize 2.0–2.5 m`）：压到 **`< 4%`**（约 3.5–4.5 万）。
- 三套体网格完成后逐一在 Fluent 求解器中重载验收：零负体积、最小标准正交质量 `> 0.15`（硬红线 `> 0.10`），整流罩（`wall_sponson`）`~0.78 m` 净空绝无粘连（偏差 `< 3 mm`，硬红线 `< 8 mm`）！

---

### 四、四重全局强收敛 + ASME V&V 20 学术级验证（全二阶 + 曲率修正）
- 求解器开启全二阶格式 + Least-Squares Cell-Based + **Warped-Face Gradient Correction** + `$k\text{-}\omega$ SST` **Curvature Correction**。
- **全部算例必须满足四重全局强收敛**：
  1. 最后 200~300 步内 $L_{\text{air}}$、$L_{\text{wing}}$、$D_{\text{air}}$、$M_z$ 连续两段 100 步均值漂移 `< 0.3%`（硬红线 `< 0.5%` 或 `< 0.5 N` / `0.5 N·m`）、标准差 `< 0.3%`（硬红线 `< 0.5%` 或 `< 1.0 N` / `1.0 N·m`）；
  2. 二阶残差降 4~6 阶（动量/湍流 `< 1e-4`、能量 `< 1e-6`、连续性 `< 5e-4` 目标 / `< 1e-3` 红线且平稳）；
  3. 全域质量通量守恒误差 `< 0.1%`（硬红线 `< 0.5%`）；
  4. 全部 7 桨盘在每套网格上分别用真实离散积分归一化，离散体积积分推力/扭矩误差 `< 0.5%`（目标 `< 0.1%`、硬红线 `< 1.0%`）。
- 完整输出 **ASME V&V 20 / Celik (2008) 6 步 GCI**（含 $r_{21}, r_{32}, p, \phi_{\text{ext}}, e_a, e_{\text{ext}}, \text{GCI}_{\text{fine}}, \text{GCI}_{\text{med}}, R_{\text{asymp}}$）至 `DELIVERABLES\data\asme_vv20_gci.json`。

---

### 五、全量 18 算例拓展与高升力实算优化矩阵
按 `QUALITY_AND_MILESTONES.md` 自动连续完成全部 **3 组 18 算例**：
1. **A 组核心 6 算例（P2–P7）**：`coarse_rpm100`、`medium_rpm100`、顶格 **`fine_rpm100` (~1.03M)**、`medium_rpm050`、`medium_rpm075`、`medium_rpm100_noswirl`；
2. **B 组 3D 深度物理拓展 6 算例（P8–P9，基于 `medium_rpm100` 热启动）**：`medium_rpm100_hlp_only`、`medium_rpm100_wt_only`、`medium_rpm100_alt_swirl`、`medium_rpm100_takeoff_v10`、`medium_rpm100_oge`、`medium_rpm100_rke`；
3. **C 组高升力改型实算优化 6 算例（P10）**：3D 推进优化 `medium_opt_hlp_vector10` + 5 套超细 2D 吹气翼型高升力改型 CFD（真实 CAD `z=2.041 m` 剖面 + HLP-3 真实吹气入口剖面，$y^+<0.5$）：`opt2d_01_clean`、`opt2d_02_flap15`、`opt2d_03_flap30`、`opt2d_04_slat_flap30`、`opt2d_05_camber_opt`。

---

### 六、飞机流体应力 + 单向流固耦合（1-Way FSI）结构应力收敛分析
遵循 `skills\aero-structural-fsi-stress\SKILL.md`，使用本机 **ANSYS Mechanical APDL v252**（`MAPDL.exe`）与收敛 Fluent 载荷，严格以 100% 真实物理完成两类应力分析与收敛验证：
1. **流体侧应力**：`fine_rpm100` 全机壁面切应力 $\tau_w$（Pa）、摩阻 $C_f$、尾流湍动能 $k$ 与雷诺切应力 $-\rho\overline{u'v'}$；
2. **结构侧 1-Way FSI 等效应力与网格收敛（P10）**：将 Fluent 真实气动静压、壁面切应力及 7 桨推力/扭矩映射到航空级 **Al-7075-T6（$\sigma_y=503\text{ MPa}$）薄壳+主翼盒（`SHELL181`）** 模型，完成 **3 套壳网格（15k/35k/75k 节点）及三套 CFD 载荷的应力收敛（GCI `< 3%`）**；
3. **双色标科学呈现**：同时输出(a) **工程许用安全色标全局云图**（展现静推低载荷下整机应力收敛、整体处于低应力冷蓝色且安全系数 $\text{FoS} \gg 20$）与(b) **自适应局部放大特写图**（真实揭示翼根与短舱吊架根部局部应力梯度与弹性变形），结果写入 `DELIVERABLES\data\fsi_structural_stress.json` 与 `stress_and_bl_profiles.csv`。

---

### 七、顶刊/顶会级复杂学术可视化标准（**强制全程使用 Times New Roman 字体！**）
严格遵循 `skills\top-venue-scientific-visualization\SKILL.md` 并调用 `scripts\plot_style.py`：
- **强制字体铁律**：所有 20 套脚本绘图的标题、坐标轴、刻度、图例、注释与数学公式**必须统一使用 Times New Roman**（PNG 实测 `400 DPI`，矢量 PDF 嵌入 `Times New Roman` TrueType 字体）；
- **融合 AIAA/JFM + CVPR/ICCV/NeurIPS 顶刊/顶会风格**：使用 `GridSpec`/`subfigures` 多面板复合排版、纯白背景、实体掩膜（`[Solid bodies masked]`）、镜像全机、CVPR 风格 `inset_axes + mark_inset` 局部放大框、ASME GCI 误差棒与 $\pm\sigma$ 置信带、小提琴分布、多指标雷达图 + Pareto 前沿 + 18 算例×10 KPI 消融热力图、$u^+(y^+)$ 对标壁面律、以及纯白背景 PyVista/Fluent 3D 硬件渲染！

---

### 八、最终全量交付清单（36 套视觉 + 19 份数据 + Ansys 附件）与 P2→P12 不停机连续运行铁律
全部输出至 `F:\FEA Coursework\Workspace\DELIVERABLES\` 并通过 `scripts\verify_deliverables.py`（退出码 `0`）：
- **20 套顶刊/顶会级复杂复合科学图**（`figures\fig01`~`fig20`，400 DPI PNG + 嵌入 Times New Roman 的矢量 PDF）
- **16 张纯白背景原生 Ansys Fluent / MAPDL / PyVista 3D 高清图**（`fluent_renders\render01`~`render16`，`>= 1920×1080` PNG）
- **19 份结构化数据表**（`data\`：7 JSON + 12 CSV）
- **顶格 Fine Ansys 提交附件**（`ansys_submission\X57_DEP_fine_rpm100.msh.h5`/`.cas.h5`/`.dat.h5` 验证可重开）+ `DELIVERABLES_MANIFEST.json` + `handoff_notes.md`。
- **全流程不停机连续跑到 P12 完工铁律（严禁在 P2~P11 任何中间阶段结束本轮回复！）**：
  - 本次任务目标是**一口气连续完成 P2 → P3 → P4 → P5 → P6 → P7 → P8 → P9 → P10 → P11 → P12 全部 11 个剩余阶段**！
  - 每完成一个阶段（P2 ~ P12）时，将中文阶段汇报追加写入 `F:\FEA Coursework\Workspace\logs\STAGE_REPORTS.md`，**严禁在 P2~P11 结束时停止调用工具或把对话交还给我！**
  - **允许结束本轮最终回复的唯一两个条件**：(1) **P2 ~ P12 全部完成且 `scripts\verify_deliverables.py` 返回退出码 `0`（`ALL CHECKS PASSED`）**；或 (2) 我主动按下了 Codex 暂停键 / 触发了 `PAUSE`/`STOP` 开关。

现在请立刻执行 `. "F:\FEA Coursework\Workspace\scripts\env_f_only.ps1"` 与 `control_gate.py resume-scan`，直接开始执行（不要只回复“收到”就停下），用可见 GUI 模式在健康的 `F:\FEA Coursework\Workspace` 中**一口气从 P2 全自动推进到 P12 全部验收通过！**
