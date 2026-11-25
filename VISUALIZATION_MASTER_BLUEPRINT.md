# X-57 DEP Coursework — 44 套全量可视化总蓝图（`CFD_Coursework.docx` 逐条对标 + 顶刊/顶会拓展 + 全套 Ansys 应力云图）

> 本蓝图严格逐条覆盖 `F:\FEA Coursework\CFD_Coursework.docx` 全部要求，并围绕 **“Ansys 全套流体/结构应力云图（10 张 3D + 4 套深度脚本图）”** 与 **“CVPR/ICCV/Nature + AIAA/JFM 融合顶刊/顶会级复合脚本图（22 套 PNG+PDF，强制 Times New Roman）”** 进行深度拓展，共计 **44 套高分辨率可视化交付成果**（22 套 2D/复合脚本图 + 22 张 3D 原生 Ansys Fluent / MAPDL / PyVista 白底渲染图）。

---

## 一、22 套顶刊/顶会级复杂复合脚本图（`DELIVERABLES\figures\`，全部 400 DPI PNG + Times New Roman 矢量 PDF）

| 编号 | 文件名（`.png` + `.pdf`） | 维度/类型 | 对应任务书 / 拓展目标 | 顶刊/顶会复合排版与核心内容 |
|---|---|---|---|---|
| **01** | `fig01_geometry_and_domain` | 2D 三视图 + 域示意 | 任务书：几何、流场与边界条件 | （已完成并验收）调平还原几何、7 桨盘、整流罩净空、计算域与 BC |
| **02** | `fig02_mesh_convergence_and_yplus` | 2D 多面板 + 误差棒 | 任务书：网格收敛（$C_L, C_D$）与 $y^+ \approx 1$ | ASME V&V 20 六步 GCI 收敛曲线（Richardson 外推 + 误差棒）+ 各部件 $y^+$ CDF |
| **03** | `fig03_convergence_histories` | 2D 曲线 + `mark_inset` | 强收敛证明（升力/力矩平台稳定） | 残差历程 + $L_{\text{air}}, L_{\text{wing}}, D_{\text{air}}, M_z$ 曲线 + CVPR 放大框展示后 300 步 $\pm\sigma$ 平台 |
| **04** | `fig04_spanwise_slices_vel_press` | 2D 实体掩膜切片（2×3） | 任务书：速度场、流线与压力分布 | HLP-1/整流罩净空、HLP-3、翼尖桨三站位：`|V|`+白流线 vs 匹配 `p_gauge` |
| **05** | `fig05_horizontal_planes_blown_wing` | 2D 实体掩膜镜像全机 | 任务书：吹气机翼滑流相互作用 | HLP 推力轴平面（翼下 12+2 射流融合）vs 翼上表面平面 |
| **06** | `fig06_wing_cp_and_suction` | 2D 曲线 + 翼面云图 + 放大框 | 任务书：机翼 $C_p$ 分布与最低压（最大吸力）定位 | 6 展向站位上下翼面 $C_p(x/c)$ + `mark_inset` 前缘吸力峰放大 + 镜像平面 $C_p$ 精确标注全局吸力极值坐标 |
| **07** | `fig07_rpm_sweep_scaling` | 2D 双面板 + 柱状插图 | 任务书：静推力、静态升力增量与转速关系 | 0/50/75/100% RPM 气动力 $s^2$ 二次拟合 ($R^2$) + 静推/净推与 $D/s^2, |L|/s^2$ 塌缩插图 |
| **08** | `fig08_swirl_comparison_and_load_shift` | 2D 切片 + 载荷差（1×3） | 任务书/拓展：旋流物理与翼尖涡耦合 | $x=1.20\text{ m}$ 尾流横截面轴向涡量+二次流线（Swirl ON vs OFF）+ 展向载荷差 $\Delta(\mathrm{d}L/\mathrm{d}z)$ |
| **09** | `fig09_wake_evolution_crossplanes` | 2D 四站位横截面演化 | 拓展：尾流收缩、融合、地面效应与翼尖涡 | $x=-0.30, +0.35, +1.20, +3.00\text{ m}$ 四站位实体掩膜速度/涡量横截面演化 |
| **10** | `fig10_component_force_and_upper_lower_budget` | 2D 瀑布/堆叠分解图 | 任务书/拓展：静态升力增量机理拆解 | 5 部件压差 vs 粘性升/阻力分解 + 机翼上/下表面垂向压力积分拆解 |
| **11** | `fig11_wall_yplus_and_shear_map` | 2D 翼面云图（双面板） | 任务书：$y^+ \approx 1$ 全翼验证 + 流体壁面切应力 | 机翼平面壁面 $y^+$ 云图 + 壁面切应力 $\tau_w$/摩阻系数 $C_f$ 云图 |
| **12** | `fig12_actuator_disk_verification_and_design_concept` | 2D 曲线 + 误差柱图 | 任务书：螺旋桨模型验证 + NASA 文献对标 | 7 桨盘径向 $w_T, w_Q$ + Fluent 离散积分误差验算 + NASA X-57 文献对比机理图 |
| **13** | `fig13_propulsion_decomposition_and_synergy` | 2D 消融柱图 + 展向曲线 | 拓展实验：动力耦合分解与交替反旋 | 全开 vs 仅 HLP vs 仅翼尖桨 + 非线性干扰项 + NASA Mod IV 交替反旋对比 |
| **14** | `fig14_ground_effect_and_takeoff_roll` | 2D 切片 + 压力/升力对比 | 拓展实验：地面效应（IGE/OGE）与起飞滑跑 | 有/无跑道地面效应对比 + $V_\infty=0 \to 10\text{ m/s}$ 滑跑过渡升力与翼面 $C_p$ 演化 |
| **15** | `fig15_turbulence_model_sensitivity` | 2D 多面板验证图 | 拓展实验：湍流模型敏感性（顶刊必备） | $k\text{-}\omega$ SST vs Realizable $k\text{-}\varepsilon$ EWT：力系数、HLP-3 $C_p$ 与尾流速度剖面 |
| **16** | `fig16_highlift_design_optimization_cfd` | 2D 流线 + $C_p$ + 增益柱图 | 任务书：缝翼/襟翼/弯度/桨轴改型实算优化 | 3D 推力下偏优化 + 5 套超细 2D 吹气翼型 Fluent 实算（Clean/Flap15/Flap30/Slat+Flap30/Camber） |
| **17** | `fig17_stress_convergence_and_fsi_structural` | 2D/3D 复合 + `mark_inset` | **重点拓展：1-Way FSI 结构应力收敛与低应力蓝** | 3 网格应力 GCI 收敛曲线 + 展向弯矩/扭矩/挠度 + 全机安全色标低应力蓝 + 翼根/吊架放大框 |
| **18** | `fig18_wall_shear_and_reynolds_stress_fields` | 2D 多面板流体应力图 | **重点拓展：Fluent 流体应力与能量损失分析** | 壁面切应力 $\tau_w$ 双尺度分布 + 尾流 TKE $k$ 与雷诺切应力 $-\rho\overline{u'v'}$ + 4 站位总压 $C_{p0}$ 损失 |
| **19** | `fig19_multi_case_ablation_heatmap_and_radar` | 2D 雷达+Pareto+热力图 | **CVPR/NeurIPS 标志性多维综合消融图** | 多指标归一化雷达图 + 改型 $\Delta C_L$-$\Delta C_D$ Pareto 前沿 + 18 算例×10 KPI 标注热力图 |
| **20** | `fig20_flow_topology_and_vortex_dynamics` | 2D 四面板流态物理图 | **JFM/AIAA 标志性流动机理深度图** | 涡环量 $\Gamma(x)$ 衰减 + 机翼 $u^+(y^+)$ 对标壁面律 + 5 部件 Raincloud 分布 + 7 桨后诱导迎角 $\alpha_{\text{ind}}(z)$ |
| **21** | `fig21_stress_envelope_and_ridge_distributions` | 2D Ridge + Raincloud | **重点拓展（Nature/CVPR 风格）：多工况应力统计包络** | 5 部件 $\sigma_{\text{vM}}, \sigma_1, \tau_{\max}, \tau_w$ 重叠 KDE Ridge/Raincloud 分布 + 静推/滑跑/优化安全系数余量图 |
| **22** | `fig22_3d_2d_hybrid_aeropropulsive_synthesis` | **3D+2D 顶刊封面级总图** | **CVPR/Nature 标志性全景成果综合图** | 6 面板全景拼装：白底 PyVista SSAO 3D Pathlines + Q-criterion + FSI 低应力蓝云图联动 2D 气动与优化曲线 |

---

## 二、22 张原生 Ansys Fluent / MAPDL / PyVista 3D 白底高清渲染图（`DELIVERABLES\fluent_renders\`，`>= 1920×1080` PNG）

### A. 网格与气动流场 3D 渲染（12 张：`render01`–`render12`）
1. `render01_mesh_farfield_hexcore.png` — 对称面/切面远场笛卡尔六面体 + 尾流 BOI 网格
2. `render02_mesh_wing_inflation_closeup.png` — 机翼前缘与短舱 18 层 $y^+ \approx 1$ 棱柱边界层特写
3. `render03_mesh_sponson_and_disks_closeup.png` — 整流罩开敞净空 + 7 桨盘高密度 BOI 网格特写
4. `render04_pathlines_slipstreams_3d.png` — 全机镜像 3D **Pathlines**（14 副螺旋桨螺旋滑流，按速度着色）
5. `render05_pathlines_wingtip_vortex_3d.png` — 翼尖及翼尖桨 3D **Pathlines** 局部特写（翼尖涡与旋流耦合）
6. `render06_surface_pressure_contour_top_3d.png` — 全机 3D 上视角表面静压/$C_p$ 云图
7. `render07_surface_pressure_contour_bottom_3d.png` — 全机 3D 下视角表面静压/$C_p$ 云图（翼下吹气负压吸力带）
8. `render08_velocity_streamlines_3d.png` — 全机 3D 全局速度流线图（静推卷吸、吹气加速与地面效应）
9. `render09_qcriterion_vortices_3d.png` — 3D 半透明 **Q-criterion 涡结构等值面**（按速度着色）
10. `render10_surface_yplus_and_oilflow_3d.png` — 全机 3D 表面 $y^+$ 云图与壁面极限流线（数值油流）
11. `render11_ige_vs_oge_wake_3d.png` — 3D 有/无跑道地面效应（IGE vs OGE）尾流射流铺展对比
12. `render12_opt_highlift_flow_comparison.png` — 3D 推力下偏 / 2D 30° 襟翼+缝翼高升力优化流场高清对比

### B. Ansys 全套流体应力 + 结构 1-Way FSI 应力与安全系数 3D 云图（**重点 10 张：`render13`–`render22`**）
13. `render13_fluent_wall_shear_stress_top_3d.png` — Ansys Fluent 3D **上表面壁面切应力 $\tau_w$**（工程色标低应力冷蓝 + 吹气前缘细节）
14. `render14_fluent_wall_shear_stress_bottom_3d.png` — Ansys Fluent 3D **下表面壁面切应力 $\tau_w$**（翼下射流冲刷剪切带）
15. `render15_fluent_reynolds_stress_and_tke_3d.png` — Ansys Fluent 3D **尾流湍动能 $k$ 与雷诺切应力 $-\rho\overline{u'v'}$** 切片与等值壳
16. `render16_fluent_total_pressure_loss_3d.png` — Ansys Fluent 3D **总压系数 $C_{p0}$ 与滑流能量核**
17. `render17_fsi_von_mises_global_top_3d.png` — Ansys MAPDL 1-Way FSI 3D **上视角整机 von Mises 等效应力 $\sigma_{\text{vM}}$**（工程安全色标：**整体收敛为安全低应力冷蓝色，安全系数 $\text{FoS} \gg 20$！**）
18. `render18_fsi_von_mises_global_bottom_3d.png` — Ansys MAPDL 1-Way FSI 3D **下视角整机 von Mises 等效应力 $\sigma_{\text{vM}}$**（整体低应力冷蓝）
19. `render19_fsi_von_mises_root_pylon_zoom_3d.png` — Ansys MAPDL 3D **翼根与 HLP 短舱吊架根部自适应局部应力集中特写**
20. `render20_fsi_principal_stress_s1_s3_3d.png` — Ansys MAPDL 3D **最大主应力 $\sigma_1$（受拉）与最小主应力 $\sigma_3$（受压）** 翼面双视图
21. `render21_fsi_shear_stress_tresca_3d.png` — Ansys MAPDL 3D **Tresca 最大切应力 / 翼盒面内切应力 $\tau_{\max}$**
22. `render22_fsi_deformation_and_safety_factor_3d.png` — Ansys MAPDL 3D **结构总弹性变形 $U_{\text{sum}}$（放大叠加）与安全系数 $\text{FoS}$ 云图**
