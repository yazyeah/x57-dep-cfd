"""Build the arXiv submission from REPORT/main.tex.

arXiv compiles with pdfLaTeX (no XeLaTeX) and does not run BibTeX, so the bundle contains:
  main.tex (package option ``arxiv``: no course code, no coursework subtitle; flat ``figures/`` path),
  x57_paper.sty, references.bib, main.bbl, figures/<every included image>, assets/dundee_logo.png.
The bundle is compiled here with pdflatex + bibtex exactly as arXiv would, and written to
  REPORT/arxiv/source/            unpacked source tree
  REPORT/arxiv/x57_dep_cfd_arxiv_source.zip   upload this file to arXiv
  REPORT/arxiv/X57_DEP_CFD_arXiv_preview.pdf  the PDF that the source produces
"""
import re
import shutil
import subprocess
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "arxiv"
SRC = OUT / "source"
SEARCH = [HERE.parent / "DELIVERABLES" / "figures", HERE.parent / "DELIVERABLES" / "fluent_renders", HERE / "assets"]
EXT = ("", ".pdf", ".png", ".jpg")


def find(name):
    for folder in SEARCH:
        for ext in EXT:
            p = folder / (name + ext)
            if p.is_file():
                return p
    raise FileNotFoundError(name)


def run(cmd, cwd):
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        print(r.stdout[-4000:])
        raise SystemExit(f"{cmd[0]} failed ({r.returncode})")
    return r.stdout


def main():
    if OUT.exists():
        shutil.rmtree(OUT)
    (SRC / "figures").mkdir(parents=True)
    (SRC / "assets").mkdir()
    tex = (HERE / "main.tex").read_text(encoding="utf-8")
    tex, n_opt = re.subn(r"(?m)^\\usepackage\[singlecol\]\{x57_paper\}", lambda m: r"\usepackage[singlecol,arxiv]{x57_paper}", tex)
    tex, n_path = re.subn(r"(?m)^\\graphicspath\{.*\}$", lambda m: r"\graphicspath{{figures/}}", tex)
    if (n_opt, n_path) != (1, 1):
        raise SystemExit(f"main.tex preamble not recognised (option {n_opt}, graphicspath {n_path})")
    tex = "\\pdfoutput=1\n" + tex
    names = re.findall(r"\\includegraphics(?:\[[^\]]*\])?\{([^}]+)\}", tex)
    for n in sorted(set(names)):
        p = find(n)
        shutil.copy2(p, SRC / "figures" / p.name)
    shutil.copy2(HERE / "assets" / "dundee_logo.png", SRC / "assets" / "dundee_logo.png")
    (SRC / "main.tex").write_text(tex, encoding="utf-8")
    for f in ("x57_paper.sty", "references.bib"):
        shutil.copy2(HERE / f, SRC / f)

    build = OUT / "_build"
    shutil.copytree(SRC, build)
    run(["pdflatex", "-interaction=nonstopmode", "-halt-on-error", "main.tex"], build)
    run(["bibtex", "main"], build)
    for _ in range(2):
        log = run(["pdflatex", "-interaction=nonstopmode", "-halt-on-error", "main.tex"], build)
    shutil.copy2(build / "main.bbl", SRC / "main.bbl")
    shutil.copy2(build / "main.pdf", OUT / "X57_DEP_CFD_arXiv_preview.pdf")
    warn = [l for l in (build / "main.log").read_text(encoding="latin-1").splitlines()
            if "undefined" in l or "Overfull" in l or "Rerun" in l]
    shutil.rmtree(build)

    with zipfile.ZipFile(OUT / "x57_dep_cfd_arxiv_source.zip", "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(SRC.rglob("*")):
            if p.is_file():
                z.write(p, p.relative_to(SRC).as_posix())
    size = (OUT / "x57_dep_cfd_arxiv_source.zip").stat().st_size / 2**20
    print(f"figures: {len(set(names))}, source zip {size:.1f} MB")
    print("log warnings:", warn[:10] or "none")


if __name__ == "__main__":
    main()
