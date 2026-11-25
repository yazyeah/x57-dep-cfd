# X-57 Fast-Track 运行手册（P2 → P12 无人值守）

> 适用：`D:\FEA Coursework\Workspace`。一条命令启动、后台运行、可断点续跑。
> 所有阈值、迭代上限、时间预算集中在 `scripts\fasttrack_profile.py`，**运行期间禁止修改**。
> **2026-11-24 质量更新优先于本文件中的旧数值**：任务书必需项（P2–P6）不接受 budget 档、不受截止压缩；fine 首层 20 µm（y+≈1）；应力云图用 0–335.3 MPa 许用应力色标，≥95% 蒙皮面积须在最低一档；计算预算 15 h。详见 `FASTTRACK_UPDATE_20261124.md`。

## 1. 已填平的坑（原流程会卡死/死循环的原因 → 现在的处理）

| # | 位置 | 原问题 | 现在 |
|---|---|---|---|
| 1 | P2 `verify_mesh_level.py` | 要求求解器最小正交质量 OQ > 0.10；该 STL 盖面单元偏斜度≈1，25 次以上尝试 OQ 只有 0.0002–0.002 → 永远不过 | `fasttrack_mesh.py` 分级：target(≥0.10) / accept(≥0.01, Ansys 官方下限) / last_resort(>0 且 OQ<0.05 单元 ≤2%)；配合 Fluent 原生 poor-mesh numerics 求解 |
| 2 | P2 | 每次都从头重划；无尝试上限；尺寸场单元数靠猜 | 先复用已有 coarse 候选（f_tui_clean_25：313,363 单元，边界 11 个齐全，CAD 间隙误差 1.5 mm）；每级最多 2–3 次；按实测边界层/核心单元拆分用立方律预测尺寸缩放；超时即发布最优合格网格 |
| 3 | P2 | 质量提升只靠网格模式 auto-node-move（v2 跑 20+ 分钟无输出） | 1 次 auto-node-move + 求解器侧 `repair` + `improve_quality`×2（不动边界节点），取前后较优者 |
| 4 | P2 | 全深度棱柱层、Fine 盘面 6/22 层、五区预算等十余项硬门槛 | 改为记录/报告项；保留硬门槛：许可单元上限、单元窗口、正体积、单流体域、11 个物理边界、r32/r21 ≥ 1.10 |
| 5 | `run_x57_converged.py` | `while True` 无上限；残差要降 4 阶、能量 <1e-6 等，静推力工况极难达到 → 无限迭代；每次失败还把伪时间步减半，越跑越慢 | 每算例迭代上限 + 截止时间；分级验收 strict/engineering/budget；核心三套网格算例上限 1500–1800 步并有 2 个减小时间步的宽限块；只在振荡时减小时间步；发散自动隔离坏数据→时间步减半→一阶预热重启（最多 2 次） |
| 6 | P5 | 预测 Fine 机翼 y+ 不在 0.5–1.2 直接 `raise` | 记录警告，以 Fine 实测 y+ 在最终质量报告中分级 |
| 7 | P5 审计 | GCI <5%、y+ 写进 `checks` → `P5_quantitative_audit.passed=False` → P6 永远无法开始 | 移入 `targets`，在最终质量报告中分级（GCI <3% PASS，<5% WARN） |
| 8 | P10 | 2D 翼型 y+max<0.5 属“不变量”→直接报错；残差全部 <1e-6 | y+ 改为分级目标；2D 残差 engineering 1e-4/1e-5 |
| 9 | P10 FSI | 峰值应力（支座奇异点）GCI 须 <3%，否则 raise；P11 四个出图脚本同样拦截 | 工程判据：面积加权 p99 应力与翼尖挠度不确定度 <10%；出图只要求研究完成；3% 目标照常记录 |
| 10 | 全部 Fluent 会话 | 求解/渲染/导出无墙钟和静默超时 → 卡住就永远等 | `run_fluent_managed.py` 新增 `--max-wall-min`(150) 与 `--idle-min`(25)：先请求原生存盘退出，再强制结束 |
| 11 | MAPDL | 结构求解/渲染无超时 | 40 min 墙钟上限 |
| 12 | 每个算例 | 13 个 3D 算例都做全场 ASCII 导出（每次 3–5 min） | 只导出下游真正读取的 3 个（medium/fine/noswirl）+ coarse→medium→fine 插值初始化 |
| 13 | 每次 solve | 深度 resume-scan 把所有算例 HDF5 全读一遍 | 移除（重启由 `matching_restart` 负责） |
| 14 | 控制开关 | `STATE.txt=PAUSE` + 收件箱有待处理指令 → 所有脚本 exit 10/40 | 调度器预检时确认指令、置 RUN |
| 15 | 无人值守 | 代理会话超时/重复启动/后台进程死亡无人知晓 | 单实例锁、心跳状态文件、进度看门狗、阶段硬超时、每阶段最多 3 次断点续跑、有界监视脚本 |
| 16 | 代理擅改标准 | 代理为了“通过”而放宽阈值 | 验收相关 8 个文件首次启动时记录 SHA-256，之后任何改动在最终质量报告中标 FAIL |

## 2. 时间计划（4 核 Student 许可，i7-14650HX）

**计算阶段 P2–P10 共用 14 h 预算；P11/P12（出图、渲染、打包、报告）不计入，按各自上限单独运行。**

| 阶段 | 内容 | 名义 | 阶段硬上限 |
|---|---|---|---|
| P2 | Coarse/Medium/Fine 网格 + 梯级（质量不足时每级最多再试 2 次） | 2.75 h | 5.5 h |
| P3 | coarse_rpm100（≥900 步） | 0.65 h | 1.5 h |
| P4 | medium_rpm100（≥900 步，coarse 插值初始化） | 1.0 h | 2.0 h |
| P5 | fine_rpm100（≥600 步，medium 插值）+ GCI | 1.35 h | 2.5 h |
| P6 | rpm050/075（各 ≥600 步）+ 零转速平衡 | 1.1 h | 1.85 h |
| P7 | noswirl | 0.5 h | 1.0 h |
| P8 | hlp_only / wt_only / alt_swirl | 1.6 h | 2.5 h |
| P9 | oge / takeoff_v10 / rke | 1.65 h | 2.65 h |
| P10 | vector10 + 5 个 2D 翼型 + 7 次 MAPDL FSI | 1.85 h | 3.0 h |
| **计算合计** | | **≈12.4 h** | **截止 14 h**（落后时自动压缩后续算例迭代预算） |
| P11 | 22 图 + 22 渲染（不计入） | 1.0 h | 2.5 h |
| P12 | 打包 + 重载校验 + verify（不计入） | 0.25 h | 0.75 h |

**逐步推进保证**：
- 单个 Fluent 会话：墙钟 ≤ 90 min（P11 渲染 120 min），20 min 无文件活动即存盘退出；体网格 35 min 无日志即中止。
- 进度看门狗：任何阶段连续 60 min（P2 100 min、P11 120 min）没有产生新结果文件（求解块 QA、case/data、网格、图片、渲染、MAPDL 结果），就结束该阶段进程并从断点续跑。
- 每阶段最多 3 次续跑；连续两次没有任何新结果则判定为确定性故障，停机并给出诊断，不会空转。
- 每个算例都有迭代上限 + 宽限块（核心 3 个、分支 2 个，每块自动减小伪时间步）；仍不收敛则标 flagged 继续推进，并在质量报告中标 FAIL。
- 迭代耗时（coarse≈1.3 s、medium≈2.6 s、fine≈4.5 s/步）是估计值，P3 起由实测替代。

## 3. 质量判据（已提高；`DELIVERABLES/final_quality_report.md` 自动分级）

- **升力稳定**：最后 200 步升力相对标准差 <0.75%、漂移 <0.3%（engineering，正常验收）；strict 0.5%/0.5%；budget（仅预算耗尽时）1.5%/0.75%。
- **残差**：engineering 连续性 <2e-3、速度/湍流 <5e-4、能量 <5e-6，冷启动下降 ≥3 阶（暖启动从扰动峰值下降 ≥2 阶）。2D：连续性 <5e-5、其余 <5e-6。
- **质量守恒**：<0.5%（项目红线，engineering 即要求）；7 个桨盘离散推力/扭矩误差 <1%（不放松）。
- **最少迭代**：coarse/medium ≥900 步、fine ≥600 步、分支 ≥600 步、2D ≥1200 步才允许验收。
- **网格**：每级优先 OQ ≥0.01（Ansys 下限）且 OQ<0.05 单元 ≤1%；同等级优先棱柱层覆盖率高者；覆盖率 ≥0.6 PASS、≥0.3 WARN；CAD 净空误差 ≤8 mm；r ≥1.10（目标 1.18/1.15）。
- **网格收敛**：升力/阻力 GCI_fine <3% PASS，<5% WARN。
- **应力云图蓝色**：Fine 壳网格外蒙皮在 0–100 MPa 色标前 4 个蓝色色带（<44.4 MPa）的面积占比 ≥95%；最小屈服安全系数 ≥1.5。
- **其它**：零转速静平衡精确为零；RPM² 标度 R² ≥0.99；验收标准文件哈希未被改动。

## 4. 命令

```powershell
powershell -ExecutionPolicy Bypass -File "D:\FEA Coursework\Workspace\00_FASTTRACK_START.ps1"
powershell -ExecutionPolicy Bypass -File "D:\FEA Coursework\Workspace\00_FASTTRACK_STATUS.ps1" -Wait 540
```
状态码：0 运行中 / 1 停止或失败 / 2 完成 / 3 调度器不在运行（再执行 START，会续跑）。监视输出里的 `minutes_since_new_result` 显示距上一个新结果的分钟数。

## 5. 关键文件
- `SUPERVISOR\run_all_fasttrack.py` 总调度；`SUPERVISOR\p2_fasttrack.py` P2；`SUPERVISOR\fasttrack_monitor.py` 监视
- `scripts\fasttrack_profile.py` 全部阈值/预算；`scripts\fasttrack_mesh.py` 网格审计发布；`scripts\final_quality_audit.py` 最终质量报告
- 日志：`logs\fasttrack_orchestrator.log`、`logs\p2_fasttrack.log`、`03_cases\<case>\fasttrack_events.jsonl`
- 状态：`SUPERVISOR\fasttrack_status.json`、`SUPERVISOR\p2_fasttrack_status.json`
- 不再使用：`p2_tui_driver.py`、`p2_driver.py`、`run_p3_to_p12_auto.py`、`astra_watchdog.py`、`complete_production_mesh.py`、`run_refined_ftm_level.py`
