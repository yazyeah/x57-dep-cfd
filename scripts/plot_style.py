#!/usr/bin/env python3
"""
Shared Top-Venue Publication Plotting Style (Times New Roman Mandatory).
Fuses AIAA Journal of Aircraft / JFM physical rigor with CVPR/ICCV/NeurIPS composite clarity.
"""

from __future__ import annotations

from pathlib import Path
import matplotlib as mpl
import matplotlib.pyplot as plt

ACADEMIC_PALETTE = [
    "#1f4e79",  # Deep Aerospace Navy
    "#c0392b",  # Crimson Accent
    "#2e7d32",  # Forest Green
    "#d97706",  # Amber Gold
    "#6a1b9a",  # Royal Purple
    "#00838f",  # Deep Teal
    "#546e7a",  # Slate Gray
]


def apply_publication_style() -> None:
    """Configure Matplotlib globally to use Times New Roman (text + math), 400 DPI, TrueType PDF embedding."""
    from matplotlib.font_manager import FontProperties, findfont
    for weight, style in (("normal","normal"),("normal","italic"),("bold","normal"),("bold","italic")):
        findfont(FontProperties(family="Times New Roman",weight=weight,style=style),fallback_to_default=False)
    mpl.rcParams.update({
        "font.family": "serif",
        "font.serif": ["Times New Roman"],
        "mathtext.fontset": "custom",
        "mathtext.sf": "Times New Roman", "mathtext.tt": "Times New Roman",
        "mathtext.cal": "Times New Roman:italic", "mathtext.fallback": None,
        "mathtext.rm": "Times New Roman",
        "mathtext.it": "Times New Roman:italic",
        "mathtext.bf": "Times New Roman:bold",
        "pdf.fonttype": 42,          # Embed TrueType fonts (Times New Roman preserved in vector PDF)
        "ps.fonttype": 42,
        "axes.labelsize": 9.5,
        "axes.titlesize": 10.0,
        "axes.titleweight": "bold",
        "xtick.labelsize": 8.5,
        "ytick.labelsize": 8.5,
        "legend.fontsize": 8.0,
        "legend.frameon": True,
        "legend.framealpha": 0.92,
        "legend.edgecolor": "#cccccc",
        "axes.linewidth": 0.85,
        "lines.linewidth": 1.5,
        "grid.color": "#888888",
        "grid.alpha": 0.22,
        "grid.linestyle": "--",
        "figure.facecolor": "white",
        "axes.facecolor": "white",
        "savefig.facecolor": "white",
        "savefig.dpi": 400,
        "savefig.bbox": "tight",
        "savefig.pad_inches": 0.04,
    })


def save_dual_figure(fig: plt.Figure, out_stem: Path, dpi: int = 400) -> tuple[Path, Path]:
    """Export both 400 DPI PNG and vector PDF with embedded Times New Roman fonts."""
    out_stem.parent.mkdir(parents=True, exist_ok=True)
    png_path = out_stem.with_suffix(".png")
    pdf_path = out_stem.with_suffix(".pdf")
    # Keep physical type sizes and use the publication-width canvas in both formats.
    fig.set_figwidth(min(7.2,max(6.8,fig.get_figwidth())))
    from matplotlib.text import Text
    fig.canvas.draw()
    for label in fig.findobj(Text):
        if label.get_visible() and label.get_text() and label.get_fontsize()<8:
            label.set_fontsize(8)
    fig.savefig(png_path, dpi=dpi, bbox_inches=None, facecolor="white")
    fig.savefig(pdf_path, bbox_inches=None, facecolor="white")
    return png_path, pdf_path
