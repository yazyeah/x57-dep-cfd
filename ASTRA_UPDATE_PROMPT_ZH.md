# 给 GPT Astra 的中文高标准补充与阶段汇报指令

> 直接复制下方分割线后的完整中文内容，发送给正在 `F:\FEA Coursework\Workspace` 中运行的 **GPT Astra**（或通过 `05_SEND_INSTRUCTION.bat` 写入 `CONTROL\USER_INSTRUCTION.md`）。

---

【最高优先级补充约束——请立即阅读 `QUALITY_AND_MILESTONES.md` 并严格执行以下 4 项要求】

### 一、随时叫停、立刻停止铁律（最高优先级）
1. 无论我在对话中直接发送“暂停/停止”，还是双击 `02_PAUSE_WORK.bat` / `03_STOP_GRACEFUL.bat`（将 `CONTROL\STATE.txt` 改为 `PAUSE` 或 `STOP`），或在 `CONTROL\USER_INSTRUCTION.md` 中写入新指令，你都必须无条件、第一时间响应。
2. 每个独立子步骤开始前和结束后，必须运行 `control_gate.py check`：
   - 一旦检测到 `PAUSE`（退出码 10）或 `STOP`（退出码 20），**严禁开启任何新的网格/求解/后处理任务**！只允许做 3 件事：(1) 确认当前 Fluent 已通过 `exit-fluent` 保存最新 `.cas.h5`/`.dat.h5` 并退出、后台无残留进程；(2) 更新 `CONTROL\CHECKPOINT.json` 记录断点；(3) 用简短中文汇报已完成内容、最新断点路径与下一步计划，然后立刻结束本轮回复把控制权交还给我。
   - 一旦检测到 `USER_INSTRUCTION.md` 有未读指令（退出码 40），必须先按要求调整，再执行 `ack-instruction` 确认。
3. 所有 Fluent 任务必须继续严格通过 `scripts\run_fluent_managed.py` 启动，并在每个求解 journal 中开启 `exit-fluent` 优雅退出钩子与定期 `/file/auto-save/`；所有文件/临时目录/缓存必须严格留在 `F:\FEA Coursework\Workspace`，绝不写 C 盘或 D 盘。

### 二、高标准量化技术指标（不达标严禁进入下一阶段）
请严格按照工作区新增的 `QUALITY_AND_MILESTONES.md` 执行以下硬性量化验收标准：
1. **几何与网格高标准**：
   - 你在 `01_geometry\cad_patches\` 拆出的 5 个命名部件（`wall_wing`, `wall_fuselage`, `wall_nacelles`, `wall_sponson`, `wall_empennage`）质量很好；Fluent Meshing 包面后必须核验 `wall_sponson` 与短舱/机翼之间的 `~0.71–0.78 m` 净空绝不能被误粘连（偏差目标 `< 3 mm`，上限 `< 8 mm`）。
   - 已在 S0 确认本机 ANSYS Student 2025 R2 单元上限 `< 1,048,576`、核数上限 `-t4`。请生成 **Coarse (~300k) / Medium (~600k) / Fine (~940k，严格 < 980k 安全上线)** 三套 **Poly-Hexcore**（远场六面体 + 壁面棱柱边界层）网格，保证最小正交质量 `> 0.15`（硬红线 `> 0.10`、零负体积），`fine_rpm100` 机翼壁面面积加权平均 `y+` 目标 `0.5 – 1.5`（P95 `< 2.5`，硬红线均值 `< 2.0`）。
2. **数值收敛与“升力必须严格稳定”硬指标（最核心红线）**：
   - 全部 6 个算例（`coarse_rpm100`、`medium_rpm100`、`fine_rpm100`、`medium_rpm050`、`medium_rpm075`、`medium_rpm100_noswirl`）严禁仅跑固定迭代步数就草率结束，必须全部同时满足：
     - **升力/阻力稳态平台**：监测整机垂向力 $L_{\text{air}}$、机翼垂向力 $L_{\text{wing}}$ 和整机阻力 $D_{\text{air}}$，在最后至少 **200~300 步** 滑动窗口内不能存在单调漂移——最后连续两段 100 步窗口均值相对漂移 `< 0.5%`（目标 `< 0.3%`；若力接近 0 N 则 `< 0.5 N`），最后 200 步标准差波动 `< 0.5%`（目标 `< 0.3%`；若力接近 0 N 则 `< 1.0 N`）。若仍在漂移或振荡，必须调小伪瞬态时间步长因子/松弛因子继续续算至拉平稳定！
     - **残差与守恒闭合**：二阶迎风下动量/湍流残差 `< 1e-4`、能量 `< 1e-6`、连续性 `< 1e-3`（目标 `< 5e-4`）且趋于平稳；全域质量通量守恒误差 `< 0.1%`（硬红线 `< 0.5%`）；每个桨盘在真实网格上的离散体积积分推力/扭矩与 BEMT 理论设定值误差 `< 0.5%`（硬红线 `< 1.0%`）。
3. **网格无关性、转速缩放与旋流物理验证**：
   - 3 网格 Roache GCI（`Fs = 1.25`）：`L_air` 与 `D_air` 的 `GCI_fine` 目标 `< 3%`（红线 `< 5%`，如实量化）。
   - 转速扫描（50%/75%/100%）：检验 $s^2$ 平方律拟合优度（目标 `R^2 >= 0.999`）及 `D_air/s^2`、`|L_air|/s^2` 塌缩性。
   - 旋流对照（Swirl ON vs OFF）：完整量化展向载荷差 $\Delta(\mathrm{d}L_{\text{wing}}/\mathrm{d}z)$ 及其内翼 HLP 段 vs 外翼尖桨段贡献，精确标出机翼全局最低压力（最大吸力）的 `(x, y, z)`、展向位置 `2z/b`、弦向位置 `x/c`、`p_gauge` 与 `C_p,min`。
4. **出版级交付物与自动化验收**：
   - 必须完整交付 `DELIVERABLES\` 下全部 4 个 JSON、6 个 CSV、8 套实体掩膜学术高清图（PNG + 矢量 PDF）、6 张 Fluent 原生 3D 高清图（`>= 1920x1080`，含三维滑流与翼尖涡 Pathlines、表面压力云图、三维速度流线、六面体远场与边界层网格特写）以及可重新加载的 Ansys 附件（`X57_DEP_fine_rpm100.msh.h5`/`.cas.h5`/`.dat.h5`），并最终跑通已升级的 `scripts\verify_deliverables.py`（退出码 `0`）。

### 三、精细化 10 阶段划分 + 每阶段必报（含真实耗时与剩余 ETA 预测）
请严格按 `QUALITY_AND_MILESTONES.md` 中的 **P0 ~ P9 共 10 个阶段** 推进（P0 已完成）：
- **P1**：几何清洗、桨叶旋向与 BEMT 标定、计算域与 7 桨盘装配验收（预计 20–35 min）
- **P2**：Coarse / Medium / Fine 三套 Poly-Hexcore + `y+≈1` 网格划分与净空/质量验收（预计 40–75 min）
- **P3**：求解 `coarse_rpm100` 并实测单步耗时，据此校准后续全部算例的精确 ETA（预计 25–50 min）
- **P4**：求解 `medium_rpm100` 至升力严格平稳（预计 55–110 min）
- **P5**：以 `medium_rpm100` 插值初始化求解 `fine_rpm100` 至升力严格平稳，输出 3 网格 GCI 与 `y+` 审计（预计 1.5–3.0 hr）
- **P6**：Medium 网格热启动求解 `medium_rpm050` 与 `medium_rpm075` 并验证 $s^2$ 平方律（预计 50–110 min）
- **P7**：Medium 网格热启动求解 `medium_rpm100_noswirl` 并量化旋流展向载荷差 $\Delta(\mathrm{d}L/\mathrm{d}z)$（预计 30–60 min）
- **P8**：真实流体切片导出 + 8 套实体掩膜高清图（PNG+PDF）+ 6 张 Fluent 3D 高清渲染（预计 40–75 min）
- **P9**：Ansys 提交文件封装复验 + 清单与交接报告 + 跑通 `verify_deliverables.py`（预计 15–25 min）

**强汇报要求**：每完成一个阶段（P1、P2、…、P9），必须按 `QUALITY_AND_MILESTONES.md` 第四节的中文模板向我汇报一次（必须包含：**本阶段实际耗时、累计耗时、基于实测速度更新的剩余 ETA、本阶段核心量化指标 PASS/FAIL 清单、断点路径与 F 盘剩余空间**），并检查 `control_gate.py check` 确认我未叫停后再进入下一阶段。

请简短确认已读取 `QUALITY_AND_MILESTONES.md` 并接受上述全部约束，然后立即完成 **P1** 并向我提交 P1 阶段汇报。
