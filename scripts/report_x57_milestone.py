"""Produce the Chinese milestone report from accepted native results and optionally sign it."""
import argparse
import datetime as dt
import re
import statistics
from contextlib import nullcontext
from pathlib import Path

from control_gate import ControlGate, atomic_write_text, get_workspace_free_gb
from run_x57_stage import ROOT, confirmed
from run_x57_converged import case_lock, control, read

LOG = ROOT / "logs"
REPORT = LOG / "STAGE_REPORTS.md"
DELIV = ROOT / "DELIVERABLES"
GROUPS = (
    ("S2_MESH_STUDY", (2,)), ("S3_SOLVER_MESH_CONVERGENCE", (3, 4, 5)),
    ("S4_RPM_AND_SWIRL_SWEEP", (6, 7)), ("S5_POSTPROC_EXTRACTION", (8, 9, 10)),
    ("S6_FIGURES_AND_QA", (11,)), ("S7_DELIVERABLES_PACK", (12,)),
)
# Provisional planning windows from QUALITY_AND_MILESTONES, section VI, in minutes.
NOMINAL = {3:(25,45), 4:(55,110), 5:(108,210), 6:(50,100), 7:(25,50), 8:(60,110),
           9:(60,115), 10:(55,95), 11:(70,115), 12:(15,25)}


def duration(seconds):
    mm, ss = divmod(round(seconds), 60)
    hh, mm = divmod(mm, 60)
    return f"{hh} 小时 {mm:02d} 分 {ss:02d} 秒"


def stage_clock(n):
    if n == 2:
        history = (ROOT / "CONTROL/INSTRUCTION_HISTORY.log").read_text("utf-8-sig")
        first = re.search(r"(?m)^\[([^]]+)] \[FLUENT_START] stage=S2_MESH_STUDY ", history)
        if first is None:
            raise ValueError("No timestamp for the start of recovered P2 production")
        start = dt.datetime.fromisoformat(first[1])
        end = dt.datetime.fromtimestamp((ROOT / "02_mesh/grid_ladder_qa.json").stat().st_mtime).astimezone()
        return start, end, None
    row = read(LOG / f"P{n}_execution.json")
    if row["status"] != "completed":
        raise ValueError(f"P{n} execution is incomplete")
    start, end = (dt.datetime.fromisoformat(row[k]) for k in ("first_start", "last_completion"))
    intervals = row["intervals"]
    active = None
    if intervals and all(item.get("end") for item in intervals):
        active = sum((dt.datetime.fromisoformat(i["end"])-dt.datetime.fromisoformat(i["start"])).total_seconds()
                     for i in intervals)
    return start, end, active


def eta(n):
    if n == 12:
        return "0 小时"
    if n == 2:
        return "待 P3 实测每步耗时后校准。"
    rates = []
    for stage in range(3, min(n, 9)+1):
        audit = read(LOG / f"P{stage}_quantitative_audit.json")
        if not audit["passed"]:
            raise ValueError(f"Unaccepted P{stage} timing")
        rows = list(audit["cases"].values())
        _, _, active = stage_clock(stage)
        solver = sum(case["solver_seconds"] for case in rows)
        # Calibration includes measured native solves and measured launch/export time.
        measured = max(active or 0, solver)
        rates.append(measured / (60 * statistics.mean(NOMINAL[stage])))
    factor = statistics.median(rates)
    bounds = [sum(NOMINAL[k][i] * (factor if k <= 9 else 1) for k in range(n+1,13))/60 for i in (0,1)]
    p3 = read(LOG / "P3_quantitative_audit.json")["cases"]["coarse_rpm100"]
    return (f"约 {bounds[0]:.1f}–{bounds[1]:.1f} 小时。P3 实测 {p3['seconds_per_iteration']:.3g} 秒/步。"
            f"以已通过的三维阶段实耗与计划中值之比的中位数 {factor:.2f} 校准 P4–P9；"
            "异类任务 P10–P12 采用规范计划范围。")


def mesh_metrics():
    lines = []
    for level in ("coarse","medium","fine"):
        row = read(ROOT / "02_mesh" / level / "mesh_qa.json")
        gaps = [abs(i["gap_change_m"]) * 1000 for i in row["sponson_gap"] if i["gap_change_m"] is not None]
        lines.append(f"PASS　{level} 共 {row['cells']:,} 个单元，最小正交质量 "
                     f"{row['min_orthogonal_quality']:.4g}（Meshing）与 {row['independent_solver_quality']['standard']:.4g}（求解器重载），"
                     f"最小体积 {row['min_volume_m3']:.4g} m³，所测净空最大误差 {max(gaps):.3f} mm。")
    fine = row["five_region_evidence"]["region_cells"]
    lines.append("PASS　Fine 五区实际占比 " + "、".join(f"{k} {100*v['fraction']:.2f}%" for k,v in fine.items()) + "。")
    p = ROOT / "02_mesh/grid_ladder_qa.json"
    return lines, [p], Path(row["source_mesh"])


def solver_metrics(n):
    path = LOG / f"P{n}_quantitative_audit.json"
    audit = read(path)
    lines = []
    for name, case in audit["cases"].items():
        data = Path(case["native_data"])
        lines.append(f"PASS　{name} 于第 {case['endpoint']} 步通过力与力矩平台、残差、质量守恒及桨盘积分验收。"
                     f"质量不平衡 {case['mass_imbalance_percent']:.4g}%，{case['seconds_per_iteration']:.3g} 秒/步。")
        forces = case["forces"]
        lines.append("窗口均值 " + "、".join(f"{key} {value['mean_N']:.5g} {'N·m' if key=='Mz' else 'N'}"
                                            for key,value in forces.items()) + "。")
    if "wing_yplus" in audit:
        y = audit["wing_yplus"]
        lines.append(f"机翼 y+ 面积加权均值 {y['mean']:.3g}，P95 {y['p95']:.3g}。")
    for key,v in audit.get("gci",{}).items():
        lines.append(f"PASS　{key} 的 Fine GCI 为 {v['fine_percent_GCI']:.3g}%，报告不确定度 {v['reported_fine_percent_uncertainty']:.3g}%。")
    for key,v in audit.get("squared_speed_fits",{}).items():
        r2 = v["r_squared_centered"]
        lines.append(f"{'PASS' if r2 is not None and r2>=.999 else 'FAIL'}　{key} 平方律目标 R² ≥ 0.999，实测 {r2}。")
    if "swirl_load_and_suction" in audit:
        delta = audit["swirl_load_and_suction"]
        lines.append("旋流开启相对关闭的翼面升力变化 " + "、".join(
            f"{k} {v:.5g} N" for k,v in delta["full_symmetric_delta_by_region_N"].items()) + "。")
        for mode,point in delta["cell_face_pressure_minima"].items():
            xyz = ", ".join(f"{v:.5f}" for v in point["face_centroid_m"])
            lines.append(f"{mode} 的最低压力位于 ({xyz}) m，2z/b = {point['span_fraction']:.4g}，"
                         f"x/c = {point['chord_fraction']:.4g}，表压 {point['p_gauge_Pa']:.5g} Pa，Cp = {point['Cp']:.4g}。")
    return lines,[path],data


def later_metrics(n):
    from verify_deliverables import REQUIRED_FIGURES_STEMS, REQUIRED_FLUENT_RENDERS, check_pdf_tnr, check_png, audit_render
    if n == 10:
        from compare_x57_cases import VECTOR, ROLL, accepted
        from fsi_provenance import accepted_result
        from prepare_airfoil_sections import CASES
        for name in [VECTOR,*CASES]:
            control()
            _,_,data = accepted(name)
        path = DELIV / "data/fsi_structural_stress.json"
        stress = read(path)
        if not stress.get("stress_mesh_study_complete",stress.get("stress_mesh_QA_passed")):
            raise ValueError("FSI mesh QA failed")
        lines = [f"PASS　{len(CASES)} 套二维优化与一套三维优化均已收敛。"]
        for k,row in stress["shell_GCI"].items():
            lines.append(f"PASS　{k} 的结构网格 GCI 为 {row['GCI_fine_percent']:.3g}%。")
        for name in ("fine_rpm100", ROLL, VECTOR):
            control()
            result,_=accepted_result("fine",name)
            peak = result["peak_element_average_top_or_bottom_von_mises_Pa"] / 1.e6
            lines.append(f"{name} 最大等效应力 {peak:.5g} MPa，最低屈服安全系数 "
                         f"{result['linear_elastic_nominal_yield_ratio']:.4g}。")
        return lines,[path],data
    if n == 11:
        from PIL import Image
        from compare_x57_cases import accepted
        for stem in REQUIRED_FIGURES_STEMS:
            control()
            p = DELIV / "figures" / (stem+".png")
            pdf = p.with_suffix(".pdf")
            with Image.open(p) as im:
                if max(abs(v-400) for v in im.info["dpi"]) > .1:
                    raise ValueError(f"PNG dpi mismatch: {p.name}")
            for ok,msg in (check_png(p),check_pdf_tnr(pdf)):
                if not ok:
                    raise ValueError(f"{stem}: {msg}")
        for number, name in enumerate(REQUIRED_FLUENT_RENDERS, 1):
            control()
            p = DELIV / "fluent_renders" / name
            ok,msg = check_png(p,min_w=1920,min_h=1080,min_bytes=40000)
            if not ok:
                raise ValueError(f"{p.name}: {msg}")
            audit_render(number, p)
        return [f"PASS　{len(REQUIRED_FIGURES_STEMS)} 套 400 DPI PNG 和嵌入 Times New Roman 的 PDF，"
                f"{len(REQUIRED_FLUENT_RENDERS)} 张至少 1920×1080 的三维图。"],[LOG/"P11_execution.json"],accepted("fine_rpm100")[2]
    final = LOG / "final_deliverables_verification.log"
    manifest = DELIV / "DELIVERABLES_MANIFEST.json"
    m = read(manifest)
    if "ALL CHECKS PASSED" not in final.read_text("utf-8-sig") or not m["submission_reload"]["passed"]:
        raise ValueError("Final verification and native reload must both have passed")
    return [f"PASS　verify_deliverables.py 退出码 0。清单含 {len(m['assets'])} 份文件，其中 "
            f"{m['counts']['data_files']} 份数据和 {m['counts']['fluent_attachments']} 份已重载附件。"],[manifest,final],DELIV/"ansys_submission/X57_DEP_fine_rpm100.dat.h5"


def report(n, commit=False):
    control()
    stage = f"P{n}"
    confirmed(stage)
    control()
    if n == 2:
        lines, evidence, restart = mesh_metrics()
    elif n <= 9:
        lines, evidence, restart = solver_metrics(n)
    else:
        lines, evidence, restart = later_metrics(n)
    start,end,active = stage_clock(n)
    history = REPORT.read_text("utf-8-sig")
    baseline = re.search(r"(\d{4}-\d{2}-\d{2} \d\d:\d\d:\d\d) 开始环境审计",history)
    if not baseline:
        raise ValueError("Missing historical P0 start time in STAGE_REPORTS.md")
    origin = dt.datetime.fromisoformat(baseline[1]).replace(tzinfo=start.tzinfo)
    detail = f"；有起止记录的执行时间 {duration(active)}" if active is not None else ""
    if n == 2:
        detail = "，从迁移后首份原生日志起算，含暂停及迁移间隔"
    summary = (f"## {stage} 阶段签出\n\n{end.isoformat(timespec='seconds')}　"
               f"本阶段历时 {duration((end-start).total_seconds())}{detail}。"
               f"从 P0 起累计墙钟时间 {duration((end-origin).total_seconds())}，含暂停。"
               f"D 盘剩余 {get_workspace_free_gb():.2f} GiB。\n\n剩余 ETA {eta(n)}\n\n"
               + "\n".join("- "+line for line in lines)
               + f"\n\n证据 {', '.join(str(p.relative_to(ROOT)) for p in evidence)}。"
               f"恢复文件 {restart}，控制台账 CONTROL/CHECKPOINT.json。")
    if commit:
        gate = ControlGate()
        cp = gate.load_checkpoint()
        previous = f"P{n-1}" if n>2 else "S1_GEOMETRY"
        if cp["stages"].get(previous,{}).get("status")!="done":
            raise ValueError(f"Missing previous stage sign-off: {previous}")
        control()
        begin,endtag = f"<!-- {stage} signoff -->",f"<!-- /{stage} signoff -->"
        block = f"{begin}\n{summary}\n{endtag}"
        if begin in history:
            if endtag not in history:
                raise ValueError(f"Incomplete report section for {stage}")
            history = re.sub(re.escape(begin)+".*?"+re.escape(endtag),lambda _:block,history,flags=re.S)
        else:
            history = history.rstrip()+"\n\n"+block+"\n"
        atomic_write_text(REPORT,history)
        for group,stages in GROUPS:
            if n in stages:
                control()
                gate.update_checkpoint(group,"done" if n==max(stages) else "in_progress",
                                       notes=f"{stage} 通过，详见 logs/STAGE_REPORTS.md")
        control()
        gate.update_checkpoint(stage,"done",notes=f"原生验收通过，详见 logs/STAGE_REPORTS.md",
                               active_case="",artifacts=[p.relative_to(ROOT).as_posix() for p in [*evidence,REPORT]])
    control()
    print(summary)


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage",choices=[f"P{n}" for n in range(2,13)])
    parser.add_argument("--commit",action="store_true",help="Write report and sign checkpoint; default prints a preview")
    args=parser.parse_args()
    control()
    with (case_lock("milestone_signoff") if args.commit else nullcontext()):
        report(int(args.stage[1:]),args.commit)

