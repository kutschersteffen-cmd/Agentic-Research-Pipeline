import warnings; warnings.filterwarnings('ignore')
import numpy as np, sys
sys.path.insert(0,'/home/user/Agentic-Research-Pipeline/backend')
from pathlib import Path
from arp.decarb.research.figures import LIGHT, DARK, _new_axes, _title, _save, _FONT

rng = np.random.default_rng(11)

def probe(g, n=60000, fe=15.0, noise=25.0):
    q = rng.normal(0,1,n); ind = (q + rng.normal(0,0.6,n)) > 0.5
    ab = (g - fe*q + rng.normal(0,noise,n)) < 0
    rd = (ab[ind].mean() - ab[~ind].mean()) if ind.any() and (~ind).any() else 0.0
    if ab.sum() < 30 or (~ab).sum() < 30:
        return np.nan, rd
    tpr = ind[ab].mean(); fpr = ind[~ab].mean()   # binary score: AUC closed form
    return (tpr + (1 - fpr)) / 2.0, rd

gaps = list(range(-140, 145, 5))
res = [probe(g) for g in gaps]
aucs = np.array([r[0] for r in res]); rds = np.array([r[1] for r in res])

for theme in (LIGHT, DARK):
    fig, ax = _new_axes(theme, figsize=(7.6, 4.3))
    ax.axvline(0, color=theme.baseline, linewidth=0.9, zorder=2)
    l1, = ax.plot(gaps, rds,  color=theme.series[0], linewidth=2.2, zorder=4,
                  label='Risk difference — decisions flipped')
    l2, = ax.plot(gaps, aucs, color=theme.series[1], linewidth=2.0, zorder=3,
                  label='AUC — ranking only')
    peak = int(np.nanargmax(rds))
    ax.plot([gaps[peak]],[rds[peak]], marker='o', markersize=7, color=theme.series[0],
            markeredgecolor=theme.surface, markeredgewidth=1.8, zorder=5)
    ax.annotate('peaks where the cell\nis balanced', xy=(gaps[peak], rds[peak]),
                xytext=(gaps[peak]+32, rds[peak]-0.03), color=theme.series[0],
                fontsize=8.6, fontweight='600', fontfamily=_FONT, va='center',
                arrowprops=dict(arrowstyle='-', color=theme.series[0], linewidth=1.0))
    j = gaps.index(65)
    ax.annotate('highest where the indicator\nchanges fewest outcomes',
                xy=(gaps[j], aucs[j]), xytext=(gaps[j]-4, aucs[j]-0.20),
                color=theme.series[1], fontsize=8.6, fontweight='600', fontfamily=_FONT,
                ha='right', arrowprops=dict(arrowstyle='-', color=theme.series[1], linewidth=1.0))
    ax.text(-137, 0.035, 'all firms abate', color=theme.ink_muted, fontsize=8.2, fontfamily=_FONT)
    ax.text(137, 0.035, 'none abate', color=theme.ink_muted, fontsize=8.2, ha='right', fontfamily=_FONT)
    ax.set_xlabel('Cell abatement gap G  ($/tCO2e)', color=theme.ink_secondary, fontsize=9, fontfamily=_FONT)
    ax.set_ylabel('Indicator performance', color=theme.ink_secondary, fontsize=9, fontfamily=_FONT)
    ax.set_ylim(0, 1.0); ax.set_xlim(-145, 145)
    leg = ax.legend(handles=[l1, l2], frameon=False, fontsize=8.8, loc='upper left', handlelength=1.3)
    for t in leg.get_texts(): t.set_color(theme.ink_secondary); t.set_fontfamily(_FONT)
    _title(ax, theme, 'Firm indicators decide only near the margin',
           'Two statistics on the same simulated data; only one tracks decision relevance')
    _save(fig, Path('/home/user/Agentic-Research-Pipeline/docs/figures'), 'fig7-abatement-gap', theme)
print('rendered')
