"""Write a managed two-dimensional Fluent journal using the accepted HLP-3 profile."""
import argparse
import json
from pathlib import Path

from fluent_checkpoints import latest_pair,case_for_data
from prepare_airfoil_sections import CASES, ROOT


def prepare(args):
    source = ROOT / "02_mesh" / args.case
    work = ROOT / "03_cases" / args.case
    cfg = json.loads((source / "section_config.json").read_text(encoding="utf-8"))
    inlet = cfg["inlet_profile"]
    profile = Path(inlet["profile_file"]).resolve(strict=True)
    if cfg["case"] != args.case or inlet["source_case_id"] != "fine_rpm100" or not profile.is_relative_to(ROOT):
        raise ValueError("Section and profile must match the powered Fine solution in this workspace.")
    if Path(args.stem).name != args.stem or args.iterations < 1 or not 0 < args.time_scale <= 1:
        raise ValueError("Invalid output stem, block size or pseudo-time scale.")
    work.mkdir(parents=True, exist_ok=True)
    if any((work / (args.stem + suffix)).exists() for suffix in (".cas.h5", ".dat.h5")):
        raise FileExistsError(f"Use a new output stem in {work}")
    if args.resume:
        if bool(args.resume_case)!=bool(args.resume_data):raise ValueError("Specify both native section restart paths")
        if args.resume_case:
            cas=args.resume_case.resolve(strict=True);dat=args.resume_data.resolve(strict=True);failures=[]
            if cas.parent!=work or dat.parent!=work or case_for_data(dat,deep=True)!=cas:raise ValueError("Invalid native section restart pair")
        else:cas,dat,failures=latest_pair(work,deep=True)
        if cas is None:
            raise ValueError(f"No complete native restart pair: {failures}")
        reads = f'/file/read-case "{cas.as_posix()}"\n/file/read-data "{dat.as_posix()}"'
    else:
        reads = f'/file/read-case "{(source/"section.msh").resolve(strict=True).as_posix()}"'
    (work / "section_config.json").write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    plan = dict(stem=args.stem, iterations=args.iterations, resume=args.resume, time_scale=args.time_scale)
    (work / "section_run.json").write_text(json.dumps(plan,indent=2),encoding="utf-8")
    worker = (ROOT / "scripts" / "section_solver_worker.py").resolve(strict=True)
    journal = f'''/file/confirm-overwrite no
{reads}
(set! checkpoint/exit-filename "exit-fluent.txt")
(set! checkpoint/check-filename "check-fluent.txt")
/mesh/check
/file/auto-save/data-frequency 50
/file/auto-save/case-frequency each-time
/file/auto-save/retain-most-recent-files yes
/file/auto-save/max-files 2
(%py-exec "exec(open('{worker.as_posix()}', encoding='utf-8').read())")
/exit ok
'''
    (work / "section.jou").write_text(journal, encoding="utf-8")
    print(work / "section.jou")


if __name__ == "__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("case", choices=CASES)
    p.add_argument("--stem", required=True)
    p.add_argument("--resume", action="store_true")
    p.add_argument("--resume-case",type=Path)
    p.add_argument("--resume-data",type=Path)
    p.add_argument("--iterations", type=int, default=300)
    p.add_argument("--time-scale", type=float, default=1.)
    prepare(p.parse_args())

