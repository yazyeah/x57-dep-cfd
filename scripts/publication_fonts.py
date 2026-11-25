"""Times New Roman settings shared by the X-57 coursework figure entry points."""
import os
from pathlib import Path

FAMILY = "Times New Roman"
FONT_DIR = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
FONT_FILES = {(False, False): "times.ttf", (False, True): "timesi.ttf",
              (True, False): "timesbd.ttf", (True, True): "timesbi.ttf"}

def font_file(bold=False, italic=False):
    path = FONT_DIR / FONT_FILES[bool(bold), bool(italic)]
    if not path.is_file():
        raise FileNotFoundError(f"Required {FAMILY} font is unavailable: {path}")
    return path

def configure_matplotlib():
    from plot_style import apply_publication_style
    apply_publication_style()


def apply_publication_style():
    configure_matplotlib()


def save_dual_figure(*args,**kwargs):
    from plot_style import save_dual_figure as save
    return save(*args,**kwargs)


def __getattr__(name):
    if name=="ACADEMIC_PALETTE":
        from plot_style import ACADEMIC_PALETTE
        return ACADEMIC_PALETTE
    raise AttributeError(name)


def configure_pyvista(plotter):
    """Apply after creating text, legends, scalar bars and axes, before rendering."""
    import pyvista as pv
    def apply(prop):
        if prop is None:
            return
        styled = pv.TextProperty()
        styled.ShallowCopy(prop)
        styled.set_font_file(str(font_file(prop.GetBold(), prop.GetItalic())))
        prop.ShallowCopy(styled)
    for renderer in plotter.renderers:
        for actor in renderer.actors.values():
            if actor.IsA("vtkCubeAxesActor"):
                for axis in range(3):
                    apply(actor.GetTitleTextProperty(axis))
                    apply(actor.GetLabelTextProperty(axis))
            else:
                for getter in ("GetTextProperty", "GetTitleTextProperty", "GetLabelTextProperty",
                               "GetAnnotationTextProperty", "GetEntryTextProperty", "GetCaptionTextProperty"):
                    if hasattr(actor, getter):
                        apply(getattr(actor, getter)())
            if actor.IsA("vtkAxesActor"):
                for axis in ("X", "Y", "Z"):
                    apply(getattr(actor, "Get" + axis + "AxisCaptionActor2D")().GetCaptionTextProperty())

def configure_fluent_font(settings):
    """Set a Fluent colormap/annotation font and return the actual native setting."""
    field = settings.font_name
    allowed = list(field.allowed_values())
    def norm(value):
        return "".join(c for c in str(value).casefold() if c.isalnum())
    match = next((v for v in allowed if norm(v) == norm(FAMILY)), None)
    if match is not None:
        settings.font_name = match
    return {"requested": FAMILY, "actual": field.get_state(),
            "exact": norm(field.get_state()) == norm(FAMILY), "available": allowed}
