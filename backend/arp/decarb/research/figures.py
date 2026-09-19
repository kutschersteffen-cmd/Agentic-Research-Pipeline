"""Figures for the review article.

Six figures, each tied to a claim in docs/CORPORATE_DECARBONISATION_REVIEW.md.
Every figure is rendered in a light and a dark variant so the paper reads
correctly on either background; the markdown references them through a
`<picture>` element.

Design follows one validated palette rather than matplotlib defaults.
Categorical hues are assigned in fixed slot order and never cycled;
magnitude uses a single hue; the one signed quantity (a correlation matrix)
uses a blue/red diverging ramp with a neutral grey midpoint. The palette was
checked with the data-viz validator: the three categorical slots clear the
all-pairs CVD and normal-vision floors in both modes. Slot 3 sits below 3:1
against the light surface, so every mark using it carries a visible value
label.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402

__all__ = ["Theme", "LIGHT", "DARK", "render_all"]


@dataclass(frozen=True)
class Theme:
    name: str
    surface: str
    ink: str
    ink_secondary: str
    ink_muted: str
    grid: str
    baseline: str
    series: tuple[str, str, str]
    diverging_low: str
    diverging_mid: str
    diverging_high: str


LIGHT = Theme(
    name="light",
    surface="#fcfcfb",
    ink="#0b0b0b",
    ink_secondary="#52514e",
    ink_muted="#898781",
    grid="#e1e0d9",
    baseline="#c3c2b7",
    series=("#2a78d6", "#eb6834", "#1baf7a"),
    diverging_low="#2a78d6",
    diverging_mid="#f0efec",
    diverging_high="#e34948",
)

DARK = Theme(
    name="dark",
    surface="#1a1a19",
    ink="#ffffff",
    ink_secondary="#c3c2b7",
    ink_muted="#898781",
    grid="#2c2c2a",
    baseline="#383835",
    series=("#3987e5", "#d95926", "#199e70"),
    diverging_low="#3987e5",
    diverging_mid="#383835",
    diverging_high="#e66767",
)

_FONT = ["DejaVu Sans", "sans-serif"]


def _new_axes(theme: Theme, *, figsize: tuple[float, float]) -> tuple[plt.Figure, plt.Axes]:
    fig, ax = plt.subplots(figsize=figsize, dpi=170)
    fig.patch.set_facecolor(theme.surface)
    ax.set_facecolor(theme.surface)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    for spine in ("left", "bottom"):
        ax.spines[spine].set_color(theme.baseline)
        ax.spines[spine].set_linewidth(0.8)
    ax.tick_params(colors=theme.ink_muted, labelsize=8.5, length=3, width=0.8)
    for label in ax.get_xticklabels() + ax.get_yticklabels():
        label.set_fontfamily(_FONT)
    ax.grid(axis="y", color=theme.grid, linewidth=0.7, linestyle="-", zorder=0)
    ax.set_axisbelow(True)
    return fig, ax


def _integer_years(ax: plt.Axes, years: list[int], *, max_ticks: int = 8) -> None:
    """Year axes get integer ticks. Matplotlib's default locator will happily
    print 2012.5, which is not a year."""
    step = max(1, int(np.ceil(len(years) / max_ticks)))
    ticks = list(years[::step])
    if years[-1] not in ticks:
        ticks.append(years[-1])
    ax.set_xticks(ticks)
    ax.set_xticklabels([str(t) for t in ticks])


def _title(ax: plt.Axes, theme: Theme, title: str, subtitle: str = "") -> None:
    ax.set_title(title, color=theme.ink, fontsize=11.5, fontweight="600", loc="left", pad=16 if subtitle else 10,
                 fontfamily=_FONT)
    if subtitle:
        ax.text(0.0, 1.02, subtitle, transform=ax.transAxes, color=theme.ink_secondary,
                fontsize=8.8, va="bottom", ha="left", fontfamily=_FONT)


def _save(fig: plt.Figure, out_dir: Path, stem: str, theme: Theme) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{stem}-{theme.name}.png"
    fig.savefig(path, facecolor=fig.get_facecolor(), bbox_inches="tight", pad_inches=0.28)
    plt.close(fig)
    return path


def _diverging(theme: Theme) -> LinearSegmentedColormap:
    return LinearSegmentedColormap.from_list(
        "decarb_div", [theme.diverging_low, theme.diverging_mid, theme.diverging_high], N=256
    )


# --------------------------------------------------------------------------
# Figure 1 - attribution waterfall
# --------------------------------------------------------------------------

def fig_attribution(attr, out_dir: Path, theme: Theme) -> Path:
    """Waterfall of a WACI change into its three drivers.

    Signed quantity, so the two diverging poles carry the sign: reductions in
    blue, increases in red, totals in neutral grey. Every bar is labelled,
    which a waterfall needs anyway to be readable.
    """
    pct = attr.as_pct_of_start()
    steps = [
        ("Start", None, attr.start_value),
        ("Emissions", pct["emissions"], None),
        ("Normalisation", pct["normalisation"], None),
        ("Allocation", pct["allocation"], None),
        ("End", None, attr.end_value),
    ]
    fig, ax = _new_axes(theme, figsize=(7.4, 4.1))

    running = attr.start_value
    for i, (label, share, absolute) in enumerate(steps):
        if absolute is not None:
            ax.bar(i, absolute, width=0.62, color=theme.ink_muted, zorder=3)
            ax.text(i, absolute, f"{absolute:.2f}", ha="center", va="bottom", fontsize=8.6,
                    color=theme.ink, fontfamily=_FONT, fontweight="600")
            running = absolute
            continue
        delta = share * attr.start_value
        bottom = running + delta if delta < 0 else running
        colour = theme.diverging_low if delta < 0 else theme.diverging_high
        ax.bar(i, abs(delta), bottom=bottom, width=0.62, color=colour, zorder=3)
        ax.text(i, max(running, running + delta), f"{share:+.1%}", ha="center", va="bottom",
                fontsize=8.6, color=theme.ink, fontfamily=_FONT, fontweight="600")
        running += delta

    # Connectors make the running total legible across the floating bars.
    levels = [attr.start_value]
    run = attr.start_value
    for _, share, absolute in steps[1:-1]:
        run += share * attr.start_value
        levels.append(run)
    for i, lvl in enumerate(levels):
        ax.plot([i + 0.31, i + 0.69], [lvl, lvl], color=theme.baseline, linewidth=0.9, zorder=2)

    ax.set_xticks(range(len(steps)))
    ax.set_xticklabels([s[0] for s in steps])
    ax.set_ylabel("WACI (tCO2e per unit revenue)", color=theme.ink_secondary, fontsize=9, fontfamily=_FONT)
    _title(ax, theme,
           "Normalisation, not abatement, moves the intensity metric",
           "Log-mean Divisia decomposition of the change in weighted average carbon intensity")
    return _save(fig, out_dir, "fig1-attribution", theme)


# --------------------------------------------------------------------------
# Figure 2 - Scope 2 wedge
# --------------------------------------------------------------------------

def fig_scope2_wedge(panel, out_dir: Path, theme: Theme, *, sector: str = "Technology") -> Path:
    """Location- against market-based Scope 2, indexed to 100 at the first year.

    Indexing puts both series on one axis, which is the alternative to the
    dual-scale chart this comparison usually gets drawn as.
    """
    from arp.decarb.scope2 import dual_reporters

    years = panel.years
    sub = panel.filter(lambda r: r.sector == sector)
    firms = set(dual_reporters(sub, years[0], years[-1]))
    loc, mkt = [], []
    for y in years:
        rows = [r for r in sub.rows if r.year == y and r.firm_id in firms]
        loc.append(sum(r.scope2_location for r in rows if r.scope2_location))
        mkt.append(sum(r.scope2_market for r in rows if r.scope2_market))
    if not loc or loc[0] == 0:
        raise ValueError("no dual reporters to plot")
    loc = [100.0 * v / loc[0] for v in loc]
    mkt = [100.0 * v / mkt[0] for v in mkt]

    fig, ax = _new_axes(theme, figsize=(7.4, 4.1))
    ax.plot(years, loc, color=theme.series[0], linewidth=2.0, zorder=3)
    ax.plot(years, mkt, color=theme.series[1], linewidth=2.0, zorder=3)
    ax.axhline(100, color=theme.baseline, linewidth=0.8, zorder=2)

    ax.text(years[-1] + 0.12, loc[-1], "Location-based", color=theme.series[0], fontsize=9,
            va="center", fontweight="600", fontfamily=_FONT)
    ax.text(years[-1] + 0.12, mkt[-1], "Market-based", color=theme.series[1], fontsize=9,
            va="center", fontweight="600", fontfamily=_FONT)
    ax.set_xlim(years[0], years[-1] + (years[-1] - years[0]) * 0.26)
    _integer_years(ax, years)
    ax.set_ylabel(f"Scope 2 emissions ({years[0]} = 100)", color=theme.ink_secondary, fontsize=9, fontfamily=_FONT)
    _title(ax, theme,
           f"{sector}: the two Scope 2 measures are diverging",
           "Firms reporting both bases throughout. The gap is procurement, not abatement.")
    return _save(fig, out_dir, "fig2-scope2-wedge", theme)


# --------------------------------------------------------------------------
# Figure 3 - indicator saturation
# --------------------------------------------------------------------------

def fig_saturation(panel, indicators: list[str], demanding: set[str], out_dir: Path, theme: Theme) -> Path:
    """Prevalence of each governance indicator over time.

    Seven series, one story, so this uses emphasis rather than seven hues:
    the demanding practices take the first two categorical slots, everything
    else recedes to muted grey. Only the highlighted series are labelled.
    """
    from arp.decarb.saturation import prevalence_by_year

    fig, ax = _new_axes(theme, figsize=(7.4, 4.3))
    slot = 0
    for ind in indicators:
        series = prevalence_by_year(panel, ind)
        years = sorted(series)
        vals = [series[y].prevalence * 100 for y in years]
        if ind in demanding:
            colour, lw, z = theme.series[slot], 2.0, 4
            slot += 1
            ax.plot(years, vals, color=colour, linewidth=lw, zorder=z)
            ax.text(years[-1] + 0.15, vals[-1], ind.replace("_", " "), color=colour, fontsize=8.6,
                    va="center", fontweight="600", fontfamily=_FONT)
        else:
            ax.plot(years, vals, color=theme.ink_muted, linewidth=1.3, alpha=0.55, zorder=3)

    years_all = panel.years
    ax.axhline(90, color=theme.baseline, linewidth=0.8, linestyle="-", zorder=2)
    ax.text(years_all[0], 91.5, "saturation threshold", color=theme.ink_muted, fontsize=8, fontfamily=_FONT)
    ax.text(years_all[0], 20, "common practices\n(grey)", color=theme.ink_muted, fontsize=8.4, fontfamily=_FONT)
    ax.set_xlim(years_all[0], years_all[-1] + (years_all[-1] - years_all[0]) * 0.30)
    _integer_years(ax, years_all, max_ticks=6)
    ax.set_ylim(0, 105)
    ax.set_ylabel("Share of firms satisfying the indicator (%)", color=theme.ink_secondary, fontsize=9,
                  fontfamily=_FONT)
    _title(ax, theme,
           "Common indicators saturate; demanding ones stay scarce",
           "An indicator satisfied by nearly every firm no longer separates them")
    return _save(fig, out_dir, "fig3-saturation", theme)


# --------------------------------------------------------------------------
# Figure 4 - red-flag correlation matrix
# --------------------------------------------------------------------------

def fig_redflag_matrix(panel, out_dir: Path, theme: Theme, *, year: int | None = None) -> Path:
    """Phi correlations between greenwashing red flags.

    A signed quantity centred on zero, so a diverging ramp with a neutral
    midpoint. Cells are annotated, which doubles as the table view.
    """
    from arp.decarb.redflags import correlation_matrix
    from arp.decarb.schemas import RED_FLAGS

    year = year or panel.years[-1]
    corr = correlation_matrix(panel, year=year)
    flags = list(RED_FLAGS)
    n = len(flags)
    grid = np.full((n, n), np.nan)
    for i, a in enumerate(flags):
        for j, b in enumerate(flags):
            if (a, b) in corr:
                grid[i, j] = grid[j, i] = corr[(a, b)]
    # Mask the diagonal and upper triangle. A self-correlation of 1 is not a
    # finding, and showing it in the strongest colour pulls the eye away from
    # the off-diagonal values that are the point of the figure.
    for i in range(n):
        for j in range(i, n):
            grid[i, j] = np.nan

    fig, ax = plt.subplots(figsize=(6.9, 5.9), dpi=170)
    fig.patch.set_facecolor(theme.surface)
    ax.set_facecolor(theme.surface)
    bound = 0.35
    # The first row and last column of a lower triangle are entirely empty;
    # dropping them removes two blank strips from the figure.
    grid = grid[1:, :-1]
    cmap = _diverging(theme)
    cmap.set_bad(theme.surface)
    im = ax.imshow(np.ma.masked_invalid(grid), cmap=cmap, vmin=-bound, vmax=bound)

    labels = [f.replace("_", " ") for f in flags]
    ax.set_xticks(range(n - 1), labels[:-1], rotation=42, ha="right", fontsize=8,
                  color=theme.ink_muted, fontfamily=_FONT)
    ax.set_yticks(range(n - 1), labels[1:], fontsize=8, color=theme.ink_muted, fontfamily=_FONT)
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.tick_params(length=0)

    for i in range(n - 1):
        for j in range(n - 1):
            if np.isnan(grid[i, j]):
                continue
            val = grid[i, j]
            ax.text(j, i, f"{val:+.2f}", ha="center", va="center", fontsize=7.4,
                    color=theme.ink if abs(val) < 0.22 else theme.surface, fontfamily=_FONT)

    cbar = fig.colorbar(im, ax=ax, fraction=0.045, pad=0.03)
    cbar.outline.set_visible(False)
    cbar.ax.tick_params(colors=theme.ink_muted, labelsize=8, length=3)
    cbar.set_label("phi correlation", color=theme.ink_secondary, fontsize=8.6, fontfamily=_FONT)

    # Placed in figure coordinates: the imshow axes is square and its
    # transAxes top sits well below the figure top, which collides the
    # subtitle into the title.
    fig.text(0.02, 1.005, "Greenwashing red flags are close to independent",
             color=theme.ink, fontsize=11.5, fontweight="600", ha="left", va="bottom", fontfamily=_FONT)
    fig.text(0.02, 0.972, "Values near zero mean a summed score discards most of the information",
             color=theme.ink_secondary, fontsize=8.6, ha="left", va="bottom", fontfamily=_FONT)
    return _save(fig, out_dir, "fig4-redflag-matrix", theme)


# --------------------------------------------------------------------------
# Figure 5 - DiD event study
# --------------------------------------------------------------------------

def fig_event_study(result, out_dir: Path, theme: Theme) -> Path:
    """Event-time ATTs with 95% confidence intervals.

    One series, so no legend: the title names it. The reference lines carry
    the two facts a reader needs, that zero is the null and that treatment
    starts at e = 0.
    """
    eff = result.effects
    fig, ax = _new_axes(theme, figsize=(7.4, 4.1))
    ax.axhline(0, color=theme.baseline, linewidth=0.9, zorder=2)
    ax.axvline(-0.5, color=theme.ink_muted, linewidth=0.9, linestyle=(0, (4, 3)), zorder=2)

    ax.errorbar(eff["event_time"], eff["att"], yerr=1.96 * eff["se"], fmt="o", markersize=6.5,
                color=theme.series[0], ecolor=theme.series[0], elinewidth=1.6, capsize=3.5,
                markeredgecolor=theme.surface, markeredgewidth=1.6, zorder=4)

    # e = -1 is the omitted base period, normalised to zero by construction.
    # Drawing it hollow stops the gap reading as missing data.
    if -1 not in set(eff["event_time"]):
        ax.plot([-1], [0.0], marker="o", markersize=6.5, markerfacecolor=theme.surface,
                markeredgecolor=theme.series[0], markeredgewidth=1.6, zorder=4, linestyle="none")
        ax.text(-1, 0.0, "  base", color=theme.ink_muted, fontsize=7.8, va="center", ha="left",
                fontfamily=_FONT)

    ymax = float((eff["att"] + 1.96 * eff["se"]).max())
    ax.text(-0.42, ymax, "adoption", color=theme.ink_muted, fontsize=8.4, va="top", fontfamily=_FONT)
    ticks = sorted(set(eff["event_time"].tolist()) | {-1})
    ax.set_xticks(ticks)
    ax.set_xlabel("Years relative to target adoption", color=theme.ink_secondary, fontsize=9, fontfamily=_FONT)
    ax.set_ylabel("Effect on log Scope 1+2 emissions", color=theme.ink_secondary, fontsize=9, fontfamily=_FONT)
    _title(ax, theme,
           "Adopting a long-term target moves near-term emissions very little",
           "Group-time ATTs, not-yet-treated controls, firm-level block bootstrap")
    return _save(fig, out_dir, "fig5-event-study", theme)


# --------------------------------------------------------------------------
# Figure 6 - level against change
# --------------------------------------------------------------------------

def fig_level_vs_change(comparison, out_dir: Path, theme: Theme) -> Path:
    """Out-of-time R-squared by model for three targets.

    Three series in fixed slot order. Every bar is value-labelled, which is
    also the relief the third slot needs against the light surface.
    """
    names = [s.name for s in comparison.level]
    level = {s.name: s.r2 for s in comparison.level}
    change = {s.name: s.r2 for s in comparison.change}
    shuffled = {s.name: s.r2 for s in comparison.level_without_sector}

    fig, ax = _new_axes(theme, figsize=(7.8, 4.3))
    x = np.arange(len(names))
    width = 0.26
    gap = 0.012
    series = [
        ("Level (intensity)", [max(level.get(n, 0), 0) for n in names], theme.series[0], -width - gap),
        ("Level, sector shuffled", [max(shuffled.get(n, 0), 0) for n in names], theme.series[1], 0.0),
        ("Change (growth)", [max(change.get(n, 0), 0) for n in names], theme.series[2], width + gap),
    ]
    for label, vals, colour, offset in series:
        ax.bar(x + offset, vals, width=width, color=colour, label=label, zorder=3)
        for xi, v in zip(x + offset, vals):
            ax.text(xi, v + 0.012, f"{v:.2f}", ha="center", va="bottom", fontsize=7.4,
                    color=theme.ink_secondary, fontfamily=_FONT)

    ax.set_xticks(x, [n.replace("_", " ") for n in names], fontsize=8.6)
    ax.set_ylabel("Out-of-time R-squared", color=theme.ink_secondary, fontsize=9, fontfamily=_FONT)
    ax.set_ylim(0, max(0.75, max(max(v) for _, v, _, _ in series) * 1.22))
    legend = ax.legend(frameon=False, fontsize=8.6, loc="upper left", ncols=3,
                       bbox_to_anchor=(0.0, 1.0), handlelength=1.1, columnspacing=1.4)
    for text in legend.get_texts():
        text.set_color(theme.ink_secondary)
        text.set_fontfamily(_FONT)
    _title(ax, theme,
           "Most of the level result is sector identification",
           "Shuffling sector destroys performance on levels; predicting change is a different problem")
    return _save(fig, out_dir, "fig6-level-vs-change", theme)


# --------------------------------------------------------------------------

def render_all(out_dir: Path | str = "docs/figures", *, n_firms: int = 500, seed: int = 20260919) -> list[Path]:
    """Render every figure in both themes from the calibrated synthetic panel."""
    import warnings

    from arp.decarb import attribution
    from arp.decarb.research.did import event_study
    from arp.decarb.research.frames import add_growth_columns, to_frame
    from arp.decarb.research.models import compare_targets
    from arp.decarb.synthetic import GOVERNANCE_INDICATORS, make_panel

    out_dir = Path(out_dir)
    panel = make_panel(n_firms=n_firms, seed=seed)
    years = panel.years
    attr = attribution.decompose_waci(panel.by_year(years[0]), panel.by_year(years[-1]))

    frame = add_growth_columns(to_frame(panel))
    frame["log_rev"] = np.log(frame["revenue"].clip(lower=1.0))
    for sector in frame["sector"].dropna().unique():
        frame[f"sector_{sector}"] = (frame["sector"] == sector).astype(float)
    features = ["log_rev", "g_scope12_lag"] + [c for c in frame.columns if c.startswith(("sector_", "ind_"))]

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        es = event_study(frame, outcome="log_scope12", n_bootstrap=200, min_event_time=-3, max_event_time=3)
        comparison = compare_targets(
            frame.dropna(subset=["intensity", "g_scope12", "g_scope12_lag"]), features=features
        )

    demanding = {"capex_aligned_plan", "scope3_supplier_program"}
    written: list[Path] = []
    for theme in (LIGHT, DARK):
        written.append(fig_attribution(attr, out_dir, theme))
        written.append(fig_scope2_wedge(panel, out_dir, theme))
        written.append(fig_saturation(panel, GOVERNANCE_INDICATORS, demanding, out_dir, theme))
        written.append(fig_redflag_matrix(panel, out_dir, theme))
        written.append(fig_event_study(es, out_dir, theme))
        written.append(fig_level_vs_change(comparison, out_dir, theme))
    return written


if __name__ == "__main__":  # pragma: no cover
    for p in render_all():
        print(p)
