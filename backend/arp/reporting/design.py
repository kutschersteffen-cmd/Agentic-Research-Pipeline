from __future__ import annotations

from dataclasses import dataclass, field

from arp.schemas.reporting import TemplateStyleProfile

# Validated, CVD-safe categorical palette in fixed slot order -- never
# cycled or reordered (see the dataviz skill's references/palette.md).
# Used as the default series palette for every chart when no ingested
# template supplies its own accent colors.
CATEGORICAL_PALETTE = ["2A78D6", "EB6834", "1BAF7A", "EDA100", "E87BA4", "008300", "4A3AA7", "E34948"]

# Single-hue sequential ramp (near-zero -> max), for heatmaps/magnitude.
SEQUENTIAL_RAMP = ["CDE2FB", "9EC5F4", "6DA7EC", "3987E5", "256ABF", "184F95", "0D366B"]

STATUS_GOOD = "0CA30C"
STATUS_CRITICAL = "D03B3B"

INK_PRIMARY = "0B0B0B"
INK_SECONDARY = "52514E"
INK_MUTED = "898781"
GRIDLINE = "E1E0D9"
BASELINE = "C3C2B7"

_ACCENT_KEYS = ("accent1", "accent2", "accent3", "accent4", "accent5", "accent6")


@dataclass
class DesignTheme:
    """The small set of design parameters every renderer (deck_builder,
    chart_builder, report_builder, pdf_builder) draws from -- one place
    to keep title/chart/table styling consistent, and the seam a
    template's own colors/fonts are threaded through when one is
    ingested. See theme_from_template for how it's derived.
    """

    accent: str = CATEGORICAL_PALETTE[0]
    ink_primary: str = INK_PRIMARY
    ink_secondary: str = INK_SECONDARY
    ink_muted: str = INK_MUTED
    gridline: str = GRIDLINE
    categorical: list[str] = field(default_factory=lambda: list(CATEGORICAL_PALETTE))
    sequential: list[str] = field(default_factory=lambda: list(SEQUENTIAL_RAMP))
    font_major: str = "Calibri"
    font_minor: str = "Calibri"


def theme_from_template(style: TemplateStyleProfile | None) -> DesignTheme:
    """Builds a DesignTheme for rendering. With no template, this is
    exactly the validated default palette above. With a template, its
    fonts always win (matching the house style is the point of ingesting
    one), and its own accent1-6 become the chart series palette *only* if
    it defines at least three of them -- a template with just one or two
    accent colors doesn't carry enough distinct, deliberately-chosen hues
    to replace a CVD-validated 8-slot palette with, so the default series
    colors are kept in that case; the template's single accent color still
    drives headings/dividers either way.
    """
    theme = DesignTheme()
    if style is None:
        return theme
    if style.theme_colors.get("accent1"):
        theme.accent = style.theme_colors["accent1"]
    template_categorical = [style.theme_colors[k] for k in _ACCENT_KEYS if style.theme_colors.get(k)]
    if len(template_categorical) >= 3:
        theme.categorical = template_categorical
    if style.theme_colors.get("dk1"):
        theme.ink_primary = style.theme_colors["dk1"]
    if style.major_font:
        theme.font_major = style.major_font
    if style.minor_font:
        theme.font_minor = style.minor_font
    return theme


def categorical_color(theme: DesignTheme, index: int) -> str:
    palette = theme.categorical or CATEGORICAL_PALETTE
    return palette[index % len(palette)]
