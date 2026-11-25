# 给 GPT Astra 的终极优化续跑指令（顶格 Student 极限网格 + 全量拓展与优化实验 + 一键暂停 + 可见 GUI）

> 开关口已重置为 `RUN`、历史残留 PID 已清理。直接复制下方分割线后的完整中文指令发给 **GPT Astra** 即可继续工作！

---

请立即恢复并在 `F:\FEA Coursework\Workspace` 中继续推进我们的 X-57 DEP 飞机 Ansys CFD 课程项目。请先阅读最新更新的 `QUALITY_AND_MILESTONES.md`、已升级的 `scripts\run_fluent_managed.py` 与 `scripts\verify_deliverables.py`，并严格按以下 5 项升级要求执行（保持 E 盘严格隔离，绝不写 C/D 盘）：

### 一、支持我直接点 Codex“暂停输出键”即刻停止（+ 高频自动存档 + 可见 Fluent GUI）
1. `scripts\run_fluent_managed.py` 已升级接入 **Windows Job Object（`JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`）与系统中断信号处理**，并默认**打开可见的 Ansys Fluent 桌面 GUI（不要传 `--headless`）**。
   - 今后只要我直接点击 Codex 的暂停/停止输出键，当前 Fluent 子进程树会被系统瞬间干净结束，无需我再发暂停提示词；你下次被我唤醒说“继续”时，**必须先检查 `02_mesh\` 与 `03_cases\` 里最新的自动存档（`.msh.h5`/`.cas.h5`/`.dat.h5`）与 `CONTROL\CHECKPOINT.json`，自动从断点续算，严禁从零重跑已完成步骤！**
2. **高频自动存档铁律**：所有 Fluent 求解 journal 必须配置：
   - `/file/confirm-overwrite no`
   - `(set! checkpoint/exit-filename "exit-fluent")`
   - `/file/auto-save/data-frequency 50`（保留最新 2 份 `.cas.h5`/`.dat.h5`，避免随时一键中断丢失进度）
   - 求解期间在可见 GUI 窗口展示残差与升阻力监测图，结尾以 `/exit ok` 干净退出不弹窗卡住。

### 二、Student 版网格顶格极限规划（5 分区精细预算，把 104.8 万天花板榨干到 97%~99.6%！）
已知 S0 实测本机 ANSYS Student 2025 R2 求解器硬上限为 **`< 1,048,576` 单元**（无法加载 140 万单元），但通过 **半机对称（×2）+ Poly-Hexcore 马赛克网格（~3× 等效四面体精度）**，半机 `103 万` 单元已等效于 **全机 `206 万` Poly-Hexcore 单元 / `500~700 万` 四面体单元**！
请你对 **Fine 网格做精细 5 分区单元规划**（请沿用你在 `iso45` 中验证高效快速的 `preserve_aircraft` 思路，避免在表面重划上空耗半小时）：
- **Coarse**：`~310k – 350k` 单元
- **Medium**：`~620k – 660k` 单元（$r_{32} \approx 1.25$）
- **Fine**：**顶格做到 `1,020,000 – 1,044,000` 单元**（严格 `<= 1,045,000 < 1,048,576`，$r_{21} \approx 1.17$），单元预算严格向关键区倾斜：
  1. **吹气主翼 (`wall_wing`) + 18 层棱柱边界层**（表面 `12–18 mm`，首层 `1.2e-5 m`，增长率 `1.16–1.18`）：占 **32%–38%**（约 34–39 万），锁定机翼面积加权平均 **$y^+ \approx 0.5\text{–}1.0$**（P95 `< 2.5`）；
  2. **7 个桨盘加密 BOI**（HLP `7–9 mm`、翼尖桨 `10–12 mm`，确保 50 mm 盘厚内 **6 层轴向**、径向 **22–32 层**）：占 **18%–22%**（约 19–23 万）；
  3. **吹气机翼与近滑流管 BOI**（$x \in [-1.0, +2.8], y \in [-0.85, +0.95], z \in [0.35, +5.65]\text{ m}$，六面体 **`35–45 mm`**）：占 **20%–24%**（约 21–25 万）；
  4. **短舱/机身/整流罩/尾翼（14–16 层棱柱）+ 中尾流 BOI（`80–110 mm`）**：占 **15%–20%**（约 16–20 万）；
  5. **外围空旷远场**（增长率 `1.22`，`MaxSize 2.0–2.5 m`）：压到 **`< 4%`**（约 3.5–4.5 万）。
- 三套网格完成后逐一核验：最小正交质量 `> 0.15`（硬红线 `> 0.10`、零负体积），整流罩（`wall_sponson`）`~0.78 m` 净空绝无粘连！

### 三、四重全局强收敛 + ASME V&V 20 学术级验证（全二阶 + 曲率修正）
- 求解器开启全二阶格式 + Least-Squares Cell-Based + **Warped-Face Gradient Correction** + `$k\text{-}\omega$ SST` **Curvature Correction**。
- **全部算例必须满足四重全局强收敛**：
  1. 最后 200~300 步内 $L_{\text{air}}$、$L_{\text{wing}}$、$D_{\text{air}}$、$M_z$ 连续两段 100 步均值漂移 `< 0.3%`（硬红线 `< 0.5%` 或 `< 0.5 N`）、标准差 `< 0.3%`（硬红线 `< 0.5%` 或 `< 1.0 N`）；
  2. 二阶残差降 4~6 阶（动量/湍流 `< 1e-4`、能量 `< 1e-6`、连续性 `< 5e-4` 目标 / `< 1e-3` 红线且平稳）；
  3. 全域质量通量守恒误差 `< 0.1%`（硬红线 `< 0.5%`）；
  4. 全部 7 桨盘离散体积积分推力/扭矩误差 `< 0.5%`（硬红线 `< 1.0%`）。
- 完整输出 **ASME V&V 20 / Celik (2008) 6 步 GCI**（含 $r_{21}, r_{32}, p, \phi_{\text{ext}}, e_a, e_{\text{ext}}, \text{GCI}_{\text{fine}}, \text{GCI}_{\text{med}}, R_{\text{asymp}}$）至 `DELIVERABLES\data\asme_vv20_gci.json`。

### 四、全量 18 算例拓展与高升力实算优化矩阵（远超普通课程作业，达到顶刊深度！）
在全部满足任务书必做项的同时，按 `QUALITY_AND_MILESTONES.md` 完成全部 **3 组 18 算例**：
1. **A 组核心 6 算例**：`coarse_rpm100`、`medium_rpm100`、顶格 **`fine_rpm100` (~1.03M)**、`medium_rpm050`、`medium_rpm075`、`medium_rpm100_noswirl`；
2. **B 组 3D 深度物理拓展 6 算例（基于 `medium_rpm100` 热启动，高效收敛）**：
   - `medium_rpm100_hlp_only`（仅 6 HLP 开）& `medium_rpm100_wt_only`（仅翼尖桨开）——**完整推进气动分解与非线性耦合项量化**；
   - `medium_rpm100_alt_swirl`——**NASA Mod IV 相邻 HLP 交替反旋 vs 同向内侧上行旋向优化对比**；
   - `medium_rpm100_takeoff_v10`——**起飞滑跑过渡（$V_\infty=10\text{ m/s}$ + 移动跑道 $10\text{ m/s}$）**；
   - `medium_rpm100_oge`——**地面效应研究（IGE vs OGE）**；
   - `medium_rpm100_rke`——**湍流模型敏感性验证（Realizable $k\text{-}\varepsilon$ EWT vs $k\text{-}\omega$ SST）**；
3. **C 组高升力改型实算优化 6 算例（把任务书的“改型建议”做成真实 CFD 优化证据！）**：
   - **3D 推进优化**：`medium_opt_hlp_vector10`（3D Medium 网格，HLP 滑流矢量下偏 $10^\circ$/桨轴优化，实证消除翼下吸力并大幅提升静态升力！）；
   - **超精细 2D 吹气翼型高升力改型 CFD（5 构型）**：提取 CAD 真实 `z=2.041 m`（HLP-3 站位）翼型截面，施加 HLP-3 真实吹气速度剖面，在 Fluent 2Ddp 超细网格（~10 万单元，$y^+<0.5$）上实算对比：**`opt2d_01_clean`（光洁基线）、`opt2d_02_flap15`（+15° 襟翼）、`opt2d_03_flap30`（+30° 开缝襟翼，直接对标 NASA X-57 Mod IV 文献）、`opt2d_04_slat_flap30`（前缘缝翼 + 30° 襟翼）与 `opt2d_05_camber_opt`（+3% 弯度改型）**！

### 五、最终交付清单与 12 阶段汇报（必须通过新版 `verify_deliverables.py` 退出码 `0`！）
全部输出至 `F:\FEA Coursework\Workspace\DELIVERABLES\`：
- **16 套学术论文级 Matplotlib 科学图**（`figures\fig01`~`fig16`，每套双导出 `400 DPI PNG` + `矢量 PDF`，实测实体掩膜、镜像全机、GCI 误差棒）
- **12 张 Fluent GUI 硬件渲染高清图**（`fluent_renders\render01`~`render12`，`>= 1920×1080` PNG，含三维 Pathlines 滑流与翼尖涡、上下表面压力云图、三维流线、Q-criterion 涡结构、表面 $y^+$ 与油流、IGE/OGE 与优化流场对比、三类网格特写）
- **16 份结构化数据表**（`data\`：6 个 JSON + 10 个 CSV，覆盖全部 18 算例、部件压差/粘性分解、ASME V&V 20 GCI、动力分解、地面效应/滑跑/湍流敏感性及高升力优化结果）
- **Ansys 提交附件**（`ansys_submission\`：顶格 Fine `X57_DEP_fine_rpm100.msh.h5`/`.cas.h5`/`.dat.h5`）+ `DELIVERABLES_MANIFEST.json` + `handoff_notes.md`。
- 继续按 `QUALITY_AND_MILESTONES.md` 的 **P2 ~ P12 阶段** 推进，**每完成一个阶段用中文向我汇报一次**（含本阶段实测耗时、累计耗时、校准后剩余 ETA、核心量化指标 PASS/FAIL、断点与 F 盘空间）。

请简短确认收到上述完整计划后，立即用可见 GUI 模式推进 **P2（Coarse / Medium / 顶格 Fine 三套网格）** 并提交 P2 阶段汇报！
