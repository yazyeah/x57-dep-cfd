---
name: top-venue-academic-latex-report
description: Clean arXiv / NeurIPS (1706.03762) pure black-and-white academic paper writing and LaTeX authoring skill with mandatory University of Dundee DI41015 running header/footer, strict zero-code-font academic prose (no filenames, no internal solver identifiers), standard black booktabs three-line tables only, IEEE numbered references, and zero-hallucination evidence binding.
metadata:
  version: 4.0.0
  venue-targets: [arXiv-Preprint, NeurIPS-1706.03762, IEEE, AIAA-Journal-of-Aircraft]
  workspace: D:\FEA Coursework\Workspace\REPORT
---

# Clean arXiv / NeurIPS (1706.03762) Academic Paper Writing & LaTeX Skill

> **Purpose**: Govern the planning, data binding, academic prose authoring, peer-review self-audit, and LaTeX compilation of the final **Year 4 CAE Ansys CFD Coursework Report** (`DI41015 - Computer Aided Engineering I`) inside `D:\FEA Coursework\Workspace\REPORT\`.

---

## 1. Non-Negotiable Grounding & Academic Prose Standards

1. **Evidence-Bounded Writing (Zero Hallucination)**:
   - NEVER invent, smooth, extrapolate, or memory-recall any numerical result, coordinate, residual, $y^+$, GCI, force, moment, stress, or safety factor.
   - Every numerical value in prose, tables, and captions MUST map 1-to-1 to a verified data file in `D:\FEA Coursework\Workspace\DELIVERABLES\data\`.
2. **Strict Academic Prose (ZERO Code Fonts, ZERO File Names, ZERO Internal Identifiers)**:
   - **NEVER** use monospace / code-style fonts (`\texttt`, `\verb`, Consolas, Courier) anywhere in the manuscript! Even element types like `SHELL181` must be set in normal Roman Times New Roman.
   - **NEVER** print raw file names (`CW1--X-57_metool.stl`, `CW1-X-57.glb`, `*.msh.h5`, `*.cas.h5`, `*.csv`, `*.json`, `*.py`) or internal solver boundary/case identifiers (`wall_wing`, `wall_fuselage`, `wall_nacelles`, `wall_sponson`, `wall_empennage`, `fine_rpm100`, `medium_rpm100_oge`, `P0--P12`, `fig01`, `render01`) in prose, captions, or tables!
   - Always translate internal identifiers into proper aerospace/engineering English (e.g., *"the main wing surface"*, *"the baseline fine-grid simulation at nominal rotational speed"*, *"the supplied three-dimensional aircraft CAD geometry"*).
3. **Zero-Hallucination Sequential IEEE Citations**:
   - Only cite verified references in `REPORT\references.bib` using standard IEEE numbered format (`\bibliographystyle{ieeetr}` + `cite`).
   - Strictly order citations sequentially (`[1]`, `[2]`, `[3]`, ...) in order of first appearance; cite each reference **once** at its primary location (avoid repetitive re-citing); place **at most two** references in a single citation bracket (e.g., `[9, 10]`, never `[1–3]`).
   - Prefix appendix headings explicitly with **`Appendix A`**, **`Appendix B`**, **`Appendix C`**, etc.

---

## 2. Mandatory Visual & Typographic Specification (`REPORT\x57_paper.sty`, arXiv 1706.03762 Reference)

1. **Pure Black Ink on Pure White Background**:
   - ALL text everywhere (title, subtitle, author, headings, captions, body text, equations, hyperlinks, citations, header text, footer text, tables) MUST be **pure black (`#000000`)**.
   - ZERO background fills or shaded boxes anywhere in the document (no shaded abstract box, no callout boxes, no `\rowcolor` in tables).
2. **Exact Rule Usage (Matching *Attention Is All You Need*, `arXiv:1706.03762`)**:
   - **Title block**: compact thick pure-black top rule (`3.2 pt`) above the title (`Aerodynamic and Structural Analysis of the NASA X-57 Distributed Electric Propulsion Aircraft`) + subtitle (`Computer Aided Engineering I: CFD Coursework Report`), thin pure-black bottom rule (`0.9 pt`) below, with tight balanced spacing (no `\begin{center}` vertical bloat); followed closely by **Yuang Zhou** and clickable black mailto link `2617376@dundee.ac.uk`.
   - **Abstract**: left blank during simulation; once all verified results are finalized, write a crisp, concise academic abstract (~140–180 words, matching *Attention Is All You Need* density) directly summarizing verified quantitative findings.
   - **GitHub Archive & Link (Post-P12 Only)**: Do NOT push prematurely. Once all results and visuals complete, curate key scripts, verified data tables, and a visually rich `README.md` featuring top CFD/FSI figures/renders, push to the user's GitHub repository, and cite the repository URL cleanly in Section 9 (Reproducibility / Conclusion).
   - **Header & Footer**: ZERO header rule (`\headrulewidth = 0pt`), ZERO footer rule (`\footrulewidth = 0pt`), compact clean spacing. Left header: pure black Times New Roman italic *DI41015 - Computer Aided Engineering I*; Right header: University of Dundee official logo (`height=8.2 mm`); Center footer: pure black `page / total`.
   - **Sections & Tables**: ZERO section heading underlines; ZERO boxes around abstract/takeaways/workflows; the ONLY other horizontal lines in the entire document are standard pure-black `booktabs` **three-line tables** (`\toprule`, `\midrule`, `\bottomrule`, zero vertical rules `|`, zero row shading).
3. **Typography**:
   - **100% Times New Roman** across body text, headings, math (`newtxmath`), tables, captions, headers, footers, and embedded figures (`left=25mm, right=25mm`, centered bold `Abstract` with `11 mm` indented pure-black prose).
